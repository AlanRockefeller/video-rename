#!/usr/bin/env python3
"""Rename video files based on GPS location and orientation from EXIF metadata."""

# video_rename.py version 1.2 by Alan Rockefeller
# October 24, 2026

import argparse
import json
import mimetypes
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    from geopy.exc import (
        GeocoderRateLimited,
        GeocoderServiceError,
        GeocoderTimedOut,
        GeocoderUnavailable,
    )
    from geopy.geocoders import Nominatim
except ImportError:
    print(
        "Error: 'geopy' library not found. Please install it with 'pip install geopy'"
    )
    sys.exit(1)

# --- Constants ---

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".hevc", ".mpg", ".mpeg"}

# exiftool uses several date fields depending on the camera/container.  The
# first populated value in this list is used as the recording date.
VIDEO_DATE_TAGS = (
    "DateTimeOriginal",
    "CreateDate",
    "MediaCreateDate",
    "TrackCreateDate",
)

# A mapping from full state names to two-letter abbreviations.
# geopy returns full state names, but we need abbreviations for the filename.
US_STATES = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
    "District of Columbia": "DC",
    "American Samoa": "AS",
    "Guam": "GU",
    "Northern Mariana Islands": "MP",
    "Puerto Rico": "PR",
    "United States Virgin Islands": "VI",
}

# --- Geocoding ---

EXIFTOOL_PATH = shutil.which("exiftool")
FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")
NOMINATIM_DOMAIN = os.environ.get(
    "VIDEO_RENAME_NOMINATIM_DOMAIN", "nominatim.openstreetmap.org"
)
GEOCODER = Nominatim(
    user_agent="video-rename/1.2 (https://github.com/AlanRockefeller/video-rename)",
    domain=NOMINATIM_DOMAIN,
)
GEOCODE_CACHE = {}
GEOCODE_COORD_PRECISION = 3
GEOCODE_MIN_INTERVAL_SECONDS = 1.1
GEOCODE_MAX_RATE_LIMIT_RETRIES = 2
GEOCODE_MAX_INLINE_BACKOFF_SECONDS = 30
GEOCODE_RATE_LIMIT_COOLDOWN_SECONDS = 60
_GEOCODE_LOCK = threading.Lock()
_GEOCODE_CACHE_LOADED = False
_GEOCODE_LAST_REQUEST = 0.0
_GEOCODE_COOLDOWN_UNTIL = 0.0
_GEOCODE_CACHE_WARNING_SHOWN = False


def _geocode_cache_path():
    """Return the persistent geocode cache path, respecting XDG_CACHE_HOME."""
    cache_root = os.environ.get("XDG_CACHE_HOME")
    if cache_root:
        return Path(cache_root) / "video-rename" / "geocode.json"
    return Path.home() / ".cache" / "video-rename" / "geocode.json"


def _load_geocode_cache():
    """Load cached reverse-geocoding results once per process."""
    global _GEOCODE_CACHE_LOADED  # pylint: disable=global-statement
    if _GEOCODE_CACHE_LOADED:
        return
    _GEOCODE_CACHE_LOADED = True
    try:
        data = json.loads(_geocode_cache_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            GEOCODE_CACHE.update(
                (key, value)
                for key, value in data.items()
                if isinstance(key, str) and (isinstance(value, str) or value is None)
            )
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return


def _save_geocode_cache():
    """Persist reverse-geocoding results atomically when possible."""
    global _GEOCODE_CACHE_WARNING_SHOWN  # pylint: disable=global-statement
    cache_path = _geocode_cache_path()
    temporary_path = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.tmp")
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text(
            json.dumps(GEOCODE_CACHE, sort_keys=True), encoding="utf-8"
        )
        temporary_path.replace(cache_path)
    except OSError as exc:
        if not _GEOCODE_CACHE_WARNING_SHOWN:
            print(f"Warning: Could not save geocoding cache: {exc}")
            _GEOCODE_CACHE_WARNING_SHOWN = True


def _location_from_geocoder_result(location):
    """Convert a Nominatim result into this tool's location filename token."""
    if not location or "address" not in location.raw:
        return None
    address = location.raw["address"]
    country = address.get("country", "")
    country_code = address.get("country_code", "").upper()
    if country_code == "US":
        state = address.get("state", "")
        state_abbr = US_STATES.get(state, state)
        return f"USA_{state_abbr}"
    return country.replace(" ", "")


def get_location_info(latitude, longitude):
    """
    Converts latitude and longitude to a location string (Country or USA_State).
    Uses a cache to avoid repeated lookups for the same coordinates.
    Returns None if location cannot be determined.
    """
    if latitude is None or longitude is None:
        return None

    global _GEOCODE_COOLDOWN_UNTIL  # pylint: disable=global-statement
    global _GEOCODE_LAST_REQUEST  # pylint: disable=global-statement

    coords = (
        round(float(latitude), GEOCODE_COORD_PRECISION),
        round(float(longitude), GEOCODE_COORD_PRECISION),
    )
    cache_key = f"{coords[0]:.{GEOCODE_COORD_PRECISION}f},{coords[1]:.{GEOCODE_COORD_PRECISION}f}"

    with _GEOCODE_LOCK:
        _load_geocode_cache()
        if cache_key in GEOCODE_CACHE:
            return GEOCODE_CACHE[cache_key]
        if time.monotonic() < _GEOCODE_COOLDOWN_UNTIL:
            return None

        for attempt in range(GEOCODE_MAX_RATE_LIMIT_RETRIES + 1):
            wait_seconds = GEOCODE_MIN_INTERVAL_SECONDS - (
                time.monotonic() - _GEOCODE_LAST_REQUEST
            )
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            _GEOCODE_LAST_REQUEST = time.monotonic()

            try:
                location = GEOCODER.reverse(coords, language="en", timeout=10)
                break
            except GeocoderRateLimited as exc:
                retry_after = getattr(exc, "retry_after", None)
                try:
                    delay = max(
                        0.0,
                        (
                            float(retry_after)
                            if retry_after is not None
                            else float(5 * (3**attempt))
                        ),
                    )
                except (TypeError, ValueError):
                    delay = 5 * (3**attempt)
            except (GeocoderTimedOut, GeocoderUnavailable, GeocoderServiceError) as exc:
                is_rate_limit = (
                    "429" in str(exc) or "too many requests" in str(exc).lower()
                )
                if not is_rate_limit:
                    print(f"Warning: Geocoding service error for {coords}: {exc}")
                    return None
                delay = 5 * (3**attempt)

            if (
                attempt >= GEOCODE_MAX_RATE_LIMIT_RETRIES
                or delay > GEOCODE_MAX_INLINE_BACKOFF_SECONDS
            ):
                cooldown = max(float(delay), GEOCODE_RATE_LIMIT_COOLDOWN_SECONDS)
                _GEOCODE_COOLDOWN_UNTIL = time.monotonic() + cooldown
                print(
                    f"Warning: Geocoding rate limited; pausing online lookups "
                    f"for {cooldown:g} seconds."
                )
                return None

            print(
                f"Warning: Geocoding rate limited; retrying in {float(delay):g} "
                "seconds."
            )
            time.sleep(float(delay))

        result = _location_from_geocoder_result(location)
        GEOCODE_CACHE[cache_key] = result
        _save_geocode_cache()
        return result


# --- EXIF and File Operations ---


def get_exif_data(file_path):
    """Extracts EXIF data from a file using exiftool."""
    if not EXIFTOOL_PATH:
        print("Warning: exiftool not found. Cannot get EXIF data.")
        return {}
    try:
        result = subprocess.run(
            [EXIFTOOL_PATH, "-json", "-n", "--", str(file_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        # exiftool returns a list with one JSON object
        data = json.loads(result.stdout)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        return {}
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        json.JSONDecodeError,
    ) as e:
        print(f"Warning: Could not get EXIF data for {file_path}. Error: {e}")
        return {}


def get_orientation(width, height, rotation=None):
    """Determines video orientation from width, height, and rotation tag."""
    if rotation in (90, 270):
        return "vertical"

    # For rotation 0, 180, or no rotation tag, decide based on dimensions
    if width is None or height is None:
        return "horizontal"  # Default

    if height > width:
        return "vertical"

    return "horizontal"


def _is_video_file(path):
    """Returns True if path is a file with a recognized video extension."""
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def _walk_error(err):
    """Callback for os.walk: warn about inaccessible directories."""
    print(f"Warning: Cannot access directory: {err}")


def get_video_files(paths, recursive):
    """Yields all video files from the given paths."""
    for path_str in paths:
        path = Path(path_str)
        if path.is_file():
            if _is_video_file(path):
                yield path
            continue
        if not path.is_dir():
            continue
        if recursive:
            for dirpath, _, filenames in os.walk(path, onerror=_walk_error):
                for filename in filenames:
                    file_path = Path(dirpath) / filename
                    if _is_video_file(file_path):
                        yield file_path
        else:
            try:
                entries = list(path.iterdir())
            except OSError as e:
                print(f"Warning: Cannot access directory {path}: {e}")
                continue
            for item in entries:
                if _is_video_file(item):
                    yield item


# --- Helpers for process_file ---


def _normalize_for_comparison(text):
    """Lowercase and strip separators for case/separator-insensitive matching."""
    return text.lower().replace("-", "").replace("_", "").replace(" ", "")


def _parse_rotation(exif_data):
    """Extract integer rotation from EXIF data, or None if unavailable."""
    rotation_val = exif_data.get("Rotation")
    if rotation_val is not None:
        try:
            return int(rotation_val)
        except (ValueError, TypeError):
            pass
    return None


def _stem_has_location(stem, location_str):
    """Check whether the stem already contains the given location string."""
    test_stem = _normalize_for_comparison(stem)

    if _normalize_for_comparison(location_str) in test_stem:
        return True

    # For US locations, also check the full state name (e.g. "New Hampshire" for USA_NH)
    if location_str.startswith("USA_"):
        abbr = location_str.split("_")[1]
        for state_name, state_abbr in US_STATES.items():
            if state_abbr == abbr:
                if _normalize_for_comparison(state_name) in test_stem:
                    return True
                break

    return False


_ORIENTATION_RE = re.compile(
    r"(?:^|[_\- ])(?:horizontal|vertical)(?:$|[_\- ])", re.IGNORECASE
)

_DATE_RE = re.compile(r"(?<!\d)(\d{4})[:_-](\d{2})[:_-](\d{2})(?!\d)")
_FILENAME_DATE_TOKEN_RE = re.compile(
    r"(?<!\d)(?:\d{8}|\d{4}[-_.:]\d{2}[-_.:]\d{2})(?!\d)"
)
_FILENAME_TIME_TOKEN_RE = re.compile(
    r"(?<!\d)\d{1,2}[-_.:]\d{2}(?:[-_.:]\d{2})" r"(?:[.,]\d{1,6})?(?:\s?[ap]m)?(?!\d)",
    re.IGNORECASE,
)
_VIDEO_TECH_TOKEN_RE = re.compile(
    r"(?<![a-z0-9])(?:\d{3,4}p|\d{2,3}fps|[248]k|uhd|fhd|hd|sd|"
    r"h[._-]?26[45]|x26[45]|hevc|av1)(?![a-z0-9])",
    re.IGNORECASE,
)
_CAMERA_ID_TOKEN_RE = re.compile(
    r"(?<![a-z0-9])(?:img|vid|dsc|mvi|mov|gopr|gx|gh)[_ -]?\d+"
    r"(?:[_ -]\d+)*(?![a-z0-9])",
    re.IGNORECASE,
)

# Names produced by cameras and phones do not usually describe their content.
# Keeping this deliberately conservative means an unfamiliar filename is
# treated as a description instead of unexpectedly being offered for rename.
_CAMERA_NAME_RE = re.compile(
    r"^(?:"
    r"(?:img|vid|dsc|mvi|mov|gopr|gx|gh)[_ -]?\d+(?:[_ -]\d+)*"
    r"|pxl[_ -]?\d{8}[_ -]?\d+"
    r"|\d{4}[-_]?\d{2}[-_]?\d{2}(?:[_ T.-]?\d{2}[_.:-]?\d{2}[_.:-]?\d{2})?"
    r"|(?:video|clip|untitled|new[_ -]video)(?:[_ -]?\d+)*"
    r"|screen[_ -]recording(?:[_ -]\d{4}[-_]\d{2}[-_]\d{2}"
    r"(?:[_ -]at)?[_ -]\d{1,2}[._-]\d{2}[._-]\d{2}(?:[_ -][ap]m)?)?"
    r"|screenrecorder(?:[_ -]?\d+)*"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r")$",
    re.IGNORECASE,
)


def _stem_has_orientation(stem):
    """Check whether the stem contains orientation as a distinct token.

    Matches 'horizontal'/'vertical' bounded by start/end of string or common
    filename separators (underscore, hyphen, space).  Does NOT match when the
    word is embedded inside a larger word like 'verticalgarden'.
    """
    return _ORIENTATION_RE.search(stem) is not None


def _get_video_date(exif_data, stem=""):
    """Return a YYYY-MM-DD recording date from EXIF or the filename."""
    for tag in VIDEO_DATE_TAGS:
        value = exif_data.get(tag)
        if value:
            match = _DATE_RE.search(str(value))
            if match:
                return "-".join(match.groups())

    match = _DATE_RE.search(stem)
    if match:
        return "-".join(match.groups())
    return None


def _sanitize_description(description):
    """Make user-entered prose safe and readable in a filename."""
    description = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", description.strip())
    description = re.sub(r"[\s_]+", "_", description)
    return description.strip(" ._-")


def _is_date_time_only_name(stem):
    """Return True when a stem contains generated metadata but no useful words."""
    if not _FILENAME_DATE_TOKEN_RE.search(stem):
        return False
    remainder = _FILENAME_DATE_TOKEN_RE.sub("", stem)
    remainder = _FILENAME_TIME_TOKEN_RE.sub("", remainder)
    remainder = _VIDEO_TECH_TOKEN_RE.sub("", remainder)
    remainder = _CAMERA_ID_TOKEN_RE.sub("", remainder)
    return re.sub(r"[\s_.(),-]+", "", remainder) == ""


def _remove_metadata_tokens(stem, date_str, location_str, orientation):
    """Remove metadata tokens so the descriptive part can be inspected."""
    result = stem
    values = (orientation, location_str, date_str)
    changed = True
    while changed:
        changed = False
        for value in values:
            if not value:
                continue
            value_pattern = r"[_ -]+".join(
                re.escape(part) for part in re.split(r"[_ -]+", value) if part
            )
            pattern = re.compile(
                r"(?:^|[_ -])" + value_pattern + r"$",
                re.IGNORECASE,
            )
            updated = pattern.sub("", result).rstrip("_ -")
            if updated != result:
                result = updated
                changed = True

        # Legacy batch names may still contain a US location when reverse
        # geocoding is temporarily unavailable during this review.
        updated = re.sub(
            r"(?:^|[_ -])USA[_ -][A-Z]{2}$", "", result, flags=re.IGNORECASE
        ).rstrip("_ -")
        if updated != result:
            result = updated
            changed = True
    return result


def _description_parts(stem, date_str=None, location_str=None, orientation=None):
    """Return (base camera name, description) inferred from a video stem.

    Generated metadata is removed from the right first.  A bare camera-style
    name has no description; any other remaining text is considered useful
    descriptive text.  For an unfamiliar name the whole stem is the
    description, which avoids repeatedly prompting for already named videos.
    """
    content_stem = _remove_metadata_tokens(
        stem, date_str, location_str, orientation
    ).strip("_ -")
    if not content_stem:
        return "", ""
    if _CAMERA_NAME_RE.fullmatch(content_stem) or _is_date_time_only_name(content_stem):
        return content_stem, ""

    # Recognize a description appended to a common camera basename.
    for separator_match in re.finditer(r"[_ -]+", content_stem):
        prefix = content_stem[: separator_match.start()]
        if _CAMERA_NAME_RE.fullmatch(prefix):
            description = content_stem[separator_match.end() :].strip("_ -")
            return prefix, description.replace("_", " ")

    return "", content_stem.replace("_", " ")


def _build_descriptive_path(
    file_path, description, date_str, location_str, orientation, base_stem=""
):
    """Build the canonical interactive filename from its useful components."""
    safe_description = _sanitize_description(description)
    if not safe_description:
        raise ValueError("Please enter a description before saving.")

    date_already_present = False
    if date_str:
        wanted_date = re.sub(r"\D", "", date_str)
        existing_text = "_".join(part for part in (base_stem, safe_description) if part)
        date_already_present = any(
            re.sub(r"\D", "", match.group()) == wanted_date
            for match in _FILENAME_DATE_TOKEN_RE.finditer(existing_text)
        )

    parts = [
        part
        for part in (
            base_stem,
            safe_description,
            None if date_already_present else date_str,
            location_str,
            orientation,
        )
        if part
    ]
    return file_path.with_name("_".join(parts) + file_path.suffix)


def _build_new_path(file_path, location_str, orientation):
    """Build the new file path with location and orientation appended.

    Preserves the existing stem and appends only missing components.
    Append order is location first, then orientation, but existing tokens
    in the stem are never moved or reordered.
    """
    stem = file_path.stem
    need_location = bool(location_str) and not _stem_has_location(stem, location_str)
    need_orientation = not _stem_has_orientation(stem)

    if not need_location and not need_orientation:
        return file_path

    # Build suffix parts in canonical order: location then orientation
    suffix_parts = []
    if need_location:
        suffix_parts.append(location_str)
    if need_orientation:
        suffix_parts.append(orientation)

    new_stem = stem + "_" + "_".join(suffix_parts)
    return file_path.with_name(new_stem + file_path.suffix)


def _get_display_name(file_path, is_recursive, base_dir):
    """Return a display name: relative path in recursive mode, filename otherwise."""
    if is_recursive and base_dir:
        try:
            return str(file_path.relative_to(base_dir))
        except ValueError:
            pass
    return str(file_path.name)


# --- Interactive review mode ---


_INTERACTIVE_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Video rename review</title>
  <style>
    :root { color-scheme: dark; --bg:#111318; --panel:#1b1f27; --muted:#9ca7b8;
      --line:#313846; --accent:#72a7ff; --good:#6bd89d; --danger:#ff7b7b; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:#edf2f8; font:15px/1.45 system-ui,sans-serif; }
    main { width:min(1120px, 100%); margin:auto; padding:24px; }
    header { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:16px; }
    h1 { font-size:20px; margin:0; } #progress { color:var(--muted); }
    video { display:block; width:100%; max-height:62vh; background:#000; border-radius:10px 10px 0 0; }
    .seek { display:flex; gap:8px; padding:10px; background:#08090c; border-radius:0 0 10px 10px; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:18px; margin-top:16px; }
    .row { margin-bottom:15px; } .label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.06em; margin-bottom:5px; }
    .filename { overflow-wrap:anywhere; font-family:ui-monospace,SFMono-Regular,monospace; }
    #proposed { color:var(--good); }
    input { width:100%; font:18px system-ui,sans-serif; padding:12px 14px; color:#fff; background:#101319; border:1px solid #4b566a; border-radius:8px; outline:none; }
    input:focus { border-color:var(--accent); box-shadow:0 0 0 3px #72a7ff25; }
    .actions { display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
    button { border:1px solid #465064; border-radius:7px; padding:9px 14px; color:#edf2f8; background:#252b36; cursor:pointer; font-weight:600; }
    button:hover { background:#303847; } button.primary { background:#2968cc; border-color:#3d7de0; }
    button:disabled { opacity:.45; cursor:default; }
    .hint { margin-left:auto; color:var(--muted); font-size:13px; }
    #message { min-height:22px; color:var(--danger); margin-top:10px; }
    .done { text-align:center; padding:80px 20px; } .done h2 { font-size:30px; }
    .attribution { color:var(--muted); font-size:12px; text-align:right; }
    .attribution a { color:var(--muted); }
    @media (max-width:650px) { main{padding:12px}.hint{width:100%;margin:4px 0 0} }
  </style>
</head>
<body><main>
  <header><h1>Video rename review</h1><span id="progress"></span></header>
  <section id="workspace" hidden>
    <video id="video" controls preload="metadata"></video>
    <div class="seek">
      <button type="button" data-seek="-10">−10s</button>
      <button type="button" data-seek="-5">−5s</button>
      <button type="button" data-seek="5">+5s</button>
      <button type="button" data-seek="10">+10s</button>
      <button type="button" id="external">Open in video player</button>
      <span id="playback-status" class="hint"></span>
    </div>
    <div class="panel">
      <div class="row"><div class="label">Current name</div><div class="filename" id="current"></div></div>
      <div class="row">
        <label class="label" for="description">Description</label>
        <input id="description" autocomplete="off" maxlength="160" placeholder="What happens in this video?">
      </div>
      <div class="row"><div class="label">Proposed name</div><div class="filename" id="proposed"></div></div>
      <div class="actions">
        <button type="button" id="previous">← Previous</button>
        <button type="button" id="skip">Skip</button>
        <button type="button" class="primary" id="save">Rename &amp; next</button>
        <button type="button" id="finish">Finish</button>
        <span class="hint">Ctrl+Enter rename · Ctrl+→ skip · Alt+←/→ seek</span>
      </div>
      <div id="message" role="alert"></div>
    </div>
  </section>
  <section id="done" class="panel done" hidden>
    <h2 id="done-title">Finding videos…</h2>
    <p id="done-message"></p>
    <button type="button" id="stop">Finish now</button>
  </section>
  <p class="attribution">Location data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a></p>
</main>
<script>
const $ = id => document.getElementById(id);
let items = [], position = 0, busy = false, scanComplete = false;
let scanned = 0, total = 0, stopped = false, pollTimer = null;
function cleanDescription(value) {
  return value.trim().replace(/[<>:"/\\|?*\x00-\x1f]/g, ' ')
    .replace(/[\s_]+/g, '_').replace(/^[ ._-]+|[ ._-]+$/g, '');
}
function containsDate(text, date) {
  if (!date) return false;
  const wanted = date.replace(/\D/g, '');
  const datePattern = /(?:^|[^\d])(\d{8}|\d{4}[-_.:]\d{2}[-_.:]\d{2})(?!\d)/g;
  let match;
  while ((match = datePattern.exec(text)) !== null) {
    if (match[1].replace(/\D/g, '') === wanted) return true;
  }
  return false;
}
function proposedName(item, description) {
  const clean = cleanDescription(description) || '[description]';
  const date = containsDate(`${item.base_stem}_${clean}`, item.date) ? null : item.date;
  return [item.base_stem, clean, date, item.location, item.orientation]
    .filter(Boolean).join('_') + item.extension;
}
async function ensureLocation(item) {
  if (!item.has_coordinates || item.locationResolved) return;
  if (!item.locationPromise) {
    item.locationPromise = fetch('/api/geocode', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:item.id})})
      .then(async response => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Location lookup failed');
        Object.assign(item, result.item); item.locationResolved = true;
        if (position < items.length && items[position].id === item.id)
          $('proposed').textContent = proposedName(item, $('description').value);
      })
      .catch(error => { item.locationResolved = true; $('message').textContent = error.message; });
  }
  await item.locationPromise;
}
function render() {
  if (position >= items.length) { waitForItem(); return; }
  const item = items[position];
  $('workspace').hidden = false; $('done').hidden = true;
  updateProgress();
  $('current').textContent = item.current_name;
  $('description').value = item.description || '';
  $('proposed').textContent = proposedName(item, $('description').value);
  $('previous').disabled = position === 0; $('message').textContent = '';
  const video = $('video'); video.pause(); video.src = `/video/${item.id}/browser`; video.load();
  ensureLocation(item);
  $('description').focus(); $('description').select();
}
function updateProgress() {
  const ready = `${Math.min(position + 1, items.length)} of ${items.length} ready`;
  $('progress').textContent = scanComplete ? ready : `${ready} · scanning ${scanned}/${total}`;
}
function waitForItem() {
  $('workspace').hidden = true; $('done').hidden = false;
  $('done-title').textContent = 'Finding the next undescribed video…';
  $('done-message').textContent = `Scanned ${scanned} of ${total} files.`;
  $('stop').hidden = false; updateProgress();
}
function completeView() {
  $('workspace').hidden = true; $('done').hidden = false; $('stop').hidden = true;
  $('done-title').textContent = items.length ? 'Review complete' : 'Nothing to review';
  $('done-message').textContent = items.length
    ? 'You can close this tab.' : 'All videos already appear to have descriptions.';
  $('progress').textContent = items.length ? `${items.length} reviewed` : `${scanned} scanned`;
}
function next() {
  if (busy) return;
  position++;
  if (position < items.length) render();
  else if (scanComplete) finish();
  else waitForItem();
}
function setBusy(value) {
  busy = value; $('save').disabled = value; $('skip').disabled = value;
  $('finish').disabled = value; $('previous').disabled = value || position === 0;
}
async function renameCurrent() {
  if (busy) return;
  const description = $('description').value;
  if (!cleanDescription(description)) { $('message').textContent = 'Enter a description, or choose Skip.'; return; }
  setBusy(true); $('message').textContent = '';
  try {
    await ensureLocation(items[position]);
    const response = await fetch('/api/rename', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:items[position].id, description})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Rename failed');
    Object.assign(items[position], result.item); setBusy(false); next();
  } catch (error) { $('message').textContent = error.message; setBusy(false); }
}
async function finish() {
  if (busy || stopped) return;
  stopped = true; clearTimeout(pollTimer); $('video').pause(); completeView();
  try { await fetch('/api/finish', {method:'POST'}); } catch (_) {}
}
async function refreshItems() {
  if (stopped) return;
  try {
    const response = await fetch('/api/items');
    const data = await response.json();
    data.items.forEach(item => { if (!items.some(existing => existing.id === item.id)) items.push(item); });
    scanComplete = data.scan_complete; scanned = data.scanned; total = data.total;
    if ($('workspace').hidden && position < items.length) render();
    else if (position >= items.length && scanComplete) finish();
    else if ($('workspace').hidden) waitForItem();
    else updateProgress();
  } catch (error) {
    if (!$('workspace').hidden) $('message').textContent = `Scanner connection lost: ${error.message}`;
  }
  if (!stopped && !scanComplete) pollTimer = setTimeout(refreshItems, 400);
}
$('description').addEventListener('input', () => {
  $('proposed').textContent = proposedName(items[position], $('description').value);
});
$('save').addEventListener('click', renameCurrent);
$('skip').addEventListener('click', next);
$('previous').addEventListener('click', () => { if (!busy && position > 0) { position--; render(); } });
$('finish').addEventListener('click', finish);
$('stop').addEventListener('click', finish);
$('external').addEventListener('click', async () => {
  const response = await fetch('/api/open', {method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:items[position].id})});
  if (!response.ok) { const result = await response.json(); $('message').textContent = result.error; }
});
$('video').addEventListener('loadstart', () => { $('playback-status').textContent = 'Loading browser preview…'; });
$('video').addEventListener('canplay', () => { $('playback-status').textContent = ''; });
$('video').addEventListener('error', () => { $('playback-status').textContent = 'Browser playback failed—try the external player.'; });
document.querySelectorAll('[data-seek]').forEach(button => button.addEventListener('click', () => {
  $('video').currentTime = Math.max(0, $('video').currentTime + Number(button.dataset.seek));
}));
document.addEventListener('keydown', event => {
  const commandKey = event.ctrlKey || event.metaKey;
  if (commandKey && event.key === 'Enter') { event.preventDefault(); renameCurrent(); }
  else if (commandKey && event.key === 'ArrowRight') { event.preventDefault(); next(); }
  else if (event.altKey && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
    event.preventDefault(); $('video').currentTime = Math.max(0, $('video').currentTime + (event.key === 'ArrowLeft' ? -5 : 5));
  }
});
refreshItems();
</script></body></html>"""


def _public_review_item(item):
    """Return the browser-safe portion of an internal review item."""
    path = item["path"]
    return {
        "id": item["id"],
        "current_name": path.name,
        "base_stem": item["base_stem"],
        "description": item["description"],
        "date": item["date"],
        "location": item["location"],
        "orientation": item["orientation"],
        "extension": path.suffix,
        "has_coordinates": item.get("latitude") is not None
        and item.get("longitude") is not None,
    }


def _orientation_from_stem(stem):
    """Return an orientation explicitly present in a filename, if any."""
    for orientation in ("horizontal", "vertical"):
        if re.search(rf"(?:^|[_\- ]){orientation}(?:$|[_\- ])", stem, re.IGNORECASE):
            return orientation
    return None


def _prepare_review_item(
    file_path,
    item_id,
    debug=False,
    skip_metadata_if_described=False,
    resolve_location=True,
):
    """Read metadata and construct one item for the interactive reviewer."""
    if skip_metadata_if_described:
        quick_date = _get_video_date({}, file_path.stem)
        quick_orientation = _orientation_from_stem(file_path.stem)
        quick_base, quick_description = _description_parts(
            file_path.stem, quick_date, None, quick_orientation
        )
        if quick_description:
            if debug:
                print(
                    f"[DEBUG] file: {file_path.name}, existing description: "
                    f"{quick_description} (metadata skipped)"
                )
            return {
                "id": item_id,
                "path": file_path,
                "base_stem": quick_base,
                "description": quick_description,
                "date": quick_date,
                "location": None,
                "orientation": quick_orientation,
                "latitude": None,
                "longitude": None,
            }

    exif_data = get_exif_data(file_path)
    width = exif_data.get("ImageWidth")
    height = exif_data.get("ImageHeight")
    rotation = _parse_rotation(exif_data)
    orientation = get_orientation(width, height, rotation)
    date_str = _get_video_date(exif_data, file_path.stem)
    latitude = exif_data.get("GPSLatitude")
    longitude = exif_data.get("GPSLongitude")
    location_str = get_location_info(latitude, longitude) if resolve_location else None
    base_stem, description = _description_parts(
        file_path.stem, date_str, location_str, orientation
    )
    if debug:
        print(
            f"[DEBUG] file: {file_path.name}, date: {date_str}, "
            f"location: {location_str}, orientation: {orientation}, "
            f"description: {description or '(none)'}"
        )
    return {
        "id": item_id,
        "path": file_path,
        "base_stem": base_stem,
        "description": description,
        "date": date_str,
        "location": location_str,
        "orientation": orientation,
        "latitude": latitude,
        "longitude": longitude,
    }


_BROWSER_AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis"}


def _audio_needs_browser_preview(file_path):
    """Return True when a video's audio codec is unlikely to play in browsers."""
    if not FFPROBE_PATH:
        return False
    try:
        result = subprocess.run(
            [
                FFPROBE_PATH,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "json",
                "--",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        data = json.loads(result.stdout)
        codecs = {
            stream.get("codec_name")
            for stream in data.get("streams", [])
            if stream.get("codec_name")
        }
        return bool(codecs) and not codecs.issubset(_BROWSER_AUDIO_CODECS)
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        OSError,
    ):
        return False


def _browser_preview_path(server, item):
    """Create an audio-compatible temporary preview while copying video unchanged."""
    source_path = item["path"]
    if not FFMPEG_PATH or not FFPROBE_PATH or not hasattr(server, "preview_dir"):
        return source_path

    with server.preview_locks_lock:
        item_lock = server.preview_locks.setdefault(item["id"], threading.Lock())

    with item_lock:
        preview_path = item.get("browser_preview_path")
        if preview_path and preview_path.exists():
            return preview_path
        if item.get("browser_preview_checked"):
            return source_path
        item["browser_preview_checked"] = True

        if not _audio_needs_browser_preview(source_path):
            return source_path

        preview_path = server.preview_dir / f"video-{item['id']}.mp4"
        print(f"[PREVIEW] Converting audio for browser playback: {source_path.name}")
        try:
            subprocess.run(
                [
                    FFMPEG_PATH,
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(source_path),
                    "-map",
                    "0:v:0?",
                    "-map",
                    "0:a:0?",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                    str(preview_path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            print(f"Warning: Could not create browser audio preview: {exc}")
            return source_path

        with server.preview_locks_lock:
            for old_preview in server.generated_previews:
                if old_preview != preview_path:
                    try:
                        old_preview.unlink()
                    except OSError:
                        pass
            server.generated_previews = {preview_path}
        item["browser_preview_path"] = preview_path
        return preview_path


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _ReviewRequestHandler(BaseHTTPRequestHandler):
    """Serve the local review app, video byte ranges, and rename actions."""

    server_version = "VideoRenameReview/1.0"

    def log_message(self, _format, *_args):
        return

    def _send_json(self, value, status=200):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid request length.") from exc
        if length > 65536:
            raise ValueError("Request is too large.")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid JSON request.") from exc
        if not isinstance(value, dict):
            raise TypeError("The request must be a JSON object.")
        return value

    def _item(self, item_id):
        try:
            index = int(item_id)
            if index < 0:
                return None
            with self.server.review_lock:
                return self.server.review_items[index]
        except (TypeError, ValueError, IndexError, KeyError):
            return None

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/":
            body = _INTERACTIVE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/items":
            with self.server.review_lock:
                response = {
                    "items": [
                        _public_review_item(item) for item in self.server.review_items
                    ],
                    "scanned": self.server.scan_progress,
                    "total": self.server.scan_total,
                    "scan_complete": self.server.scan_complete,
                }
            self._send_json(response)
            return
        match = re.fullmatch(r"/video/(\d+)(/browser)?", route)
        if match:
            item = self._item(match.group(1))
            if item:
                video_path = (
                    _browser_preview_path(self.server, item)
                    if match.group(2)
                    else item["path"]
                )
                self._serve_video(video_path)
            else:
                self.send_error(404)
            return
        self.send_error(404)

    def _serve_video(self, path):
        """Stream a video with byte-range support for browser seeking."""
        try:
            size = path.stat().st_size
            start, end, status = 0, max(0, size - 1), 200
            range_header = self.headers.get("Range")
            if range_header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
                if not match:
                    self.send_error(416)
                    return
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                elif last:
                    start = max(0, size - int(last))
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                status = 206

            length = max(0, end - start + 1)
            self.send_response(status)
            self.send_header(
                "Content-Type", mimetypes.guess_type(path.name)[0] or "video/mp4"
            )
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with path.open("rb") as source:
                source.seek(start)
                remaining = length
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (OSError, BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        route = urlparse(self.path).path
        if route == "/api/finish":
            self.server.stop_event.set()
            self._send_json({"ok": True})
            threading.Timer(0.1, self.server.shutdown).start()
            return
        if route not in ("/api/rename", "/api/open", "/api/geocode"):
            self.send_error(404)
            return
        try:
            request = self._read_json()
            item = self._item(request.get("id"))
            if not item:
                self._send_json({"error": "Video not found."}, 404)
                return
            if route == "/api/open":
                self._open_external(item["path"])
                self._send_json({"ok": True})
                return
            if route == "/api/geocode":
                self._geocode(item)
                return
            self._rename(item, request.get("description", ""))
        except (TypeError, ValueError, OSError) as exc:
            self._send_json({"error": str(exc)}, 400)

    def _geocode(self, item):
        """Resolve location for a video only when it is actually reviewed."""
        location_str = get_location_info(item["latitude"], item["longitude"])
        with self.server.review_lock:
            item["location"] = location_str
            item["base_stem"], item["description"] = _description_parts(
                item["path"].stem,
                item["date"],
                location_str,
                item["orientation"],
            )
            public_item = _public_review_item(item)
        self._send_json({"ok": True, "item": public_item})

    def _rename(self, item, description):
        if not isinstance(description, str):
            raise TypeError("Description must be text.")
        old_path = item["path"]
        new_path = _build_descriptive_path(
            old_path,
            description,
            item["date"],
            item["location"],
            item["orientation"],
            item["base_stem"],
        )
        with self.server.rename_lock, self.server.review_lock:
            if new_path != old_path and new_path.exists():
                raise ValueError(f"A file named {new_path.name} already exists.")
            if new_path != old_path and not self.server.dry_run:
                old_path.rename(new_path)
                item["path"] = new_path
            item["description"] = description.strip()
        prefix = "[DRY]" if self.server.dry_run else "[RENAME]"
        print(f"{prefix} {old_path.name} → {new_path.name}")
        public_item = _public_review_item(item)
        if not self.server.dry_run:
            public_item["current_name"] = new_path.name
        self._send_json({"ok": True, "item": public_item})

    @staticmethod
    def _open_external(path):
        if sys.platform == "darwin":
            command = ["open", str(path)]
        elif os.name == "nt":
            os.startfile(str(path))  # pylint: disable=no-member
            return
        else:
            opener = shutil.which("xdg-open")
            if not opener:
                raise ValueError("No system video opener was found.")
            command = [opener, str(path)]
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _scan_review_items(server, video_files, include_described, debug):
    """Populate a running review server without delaying its first page load."""
    for file_path in video_files:
        if server.stop_event.is_set():
            return
        try:
            item = _prepare_review_item(
                file_path.resolve(),
                -1,
                debug,
                skip_metadata_if_described=not include_described,
                resolve_location=False,
            )
            if include_described or not item["description"]:
                with server.review_lock:
                    item["id"] = len(server.review_items)
                    server.review_items.append(item)
        except (
            Exception  # noqa: BLE001 - one bad file must not stop the scanner
        ) as exc:
            print(f"Warning: Could not prepare {file_path.name}: {exc}")
        finally:
            with server.review_lock:
                server.scan_progress += 1

    with server.review_lock:
        server.scan_complete = True


def run_interactive(video_files, include_described=False, dry_run=False, debug=False):
    """Open the reviewer immediately and prepare video metadata in the background."""
    preview_directory = tempfile.TemporaryDirectory(prefix="video-rename-preview-")
    server = _ThreadingHTTPServer(("127.0.0.1", 0), _ReviewRequestHandler)
    server.review_items = []
    server.review_lock = threading.Lock()
    server.rename_lock = threading.Lock()
    server.stop_event = threading.Event()
    server.scan_progress = 0
    server.scan_total = len(video_files)
    server.scan_complete = False
    server.dry_run = dry_run
    server.preview_dir = Path(preview_directory.name)
    server.preview_locks = {}
    server.preview_locks_lock = threading.Lock()
    server.generated_previews = set()
    scanner = threading.Thread(
        target=_scan_review_items,
        args=(server, video_files, include_described, debug),
        name="video-metadata-scanner",
        daemon=True,
    )
    scanner.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Scanning {len(video_files)} video(s) in the background at {url}")
    print("Use the Finish button or press Ctrl-C here when done.")
    if not webbrowser.open(url):
        print("Could not open a browser automatically; open the URL above.")
    try:
        server.serve_forever()
    finally:
        server.stop_event.set()
        server.server_close()
        preview_directory.cleanup()


# --- Main Logic ---


def process_file(file_path, dry_run, debug, is_recursive, base_dir):
    """
    Processes a single video file: extracts metadata, determines the new name,
    and performs the rename.
    """
    exif_data = get_exif_data(file_path)

    if not exif_data:
        print(f"Skipping {file_path.name}: no EXIF data available.")
        return

    # 1. Determine orientation
    width = exif_data.get("ImageWidth")
    height = exif_data.get("ImageHeight")
    rotation = _parse_rotation(exif_data)
    orientation = get_orientation(width, height, rotation)

    if debug:
        print(
            f"[DEBUG] file: {file_path.name}, width: {width}, height: {height}, "
            f"rotation: {rotation}, orientation: {orientation}"
        )

    # 2. Determine location
    location_str = get_location_info(
        exif_data.get("GPSLatitude"), exif_data.get("GPSLongitude")
    )

    # 3. Construct new path
    new_path = _build_new_path(file_path, location_str, orientation)

    if new_path == file_path:
        return  # No change needed

    # 4. Perform rename
    display_name = _get_display_name(file_path, is_recursive, base_dir)

    if new_path.exists():
        if not dry_run:
            print(f"Warning: Destination file {new_path} already exists. Skipping.")
        else:
            print(
                f"[DRY] {display_name} → SKIP (destination {new_path.name} already exists)"
            )
    elif dry_run:
        print(f"[DRY] {display_name} → {new_path.name}")
    else:
        try:
            shutil.move(file_path, new_path)
            print(f"[RENAME] {display_name} → {new_path.name}")
        except OSError as e:
            print(f"Error: Failed to rename {file_path.name}. Reason: {e}")


def main():
    """Main function to parse arguments and orchestrate the renaming process."""
    # Custom help message for no-argument case
    if len(sys.argv) == 1:
        print(
            "Usage: video_rename.py [PATH ...] [--recursive] [--interactive] "
            "[--dry-run] [--debug]"
        )
        print(
            "\nRenames video files based on GPS location and video orientation from EXIF data."
        )
        print("\nExamples:")
        print("  video_rename.py /path/to/videos --interactive")
        print("  video_rename.py /path/to/videos --recursive")
        print("  video_rename.py my_video.mp4 --dry-run")
        print("  video_rename.py my_video.mp4 --debug")
        print("  video_rename.py vid1.mov vid2.mp4 /path/to/more_vids")
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Rename video files using GPS and orientation metadata.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  # Recursively scan a directory and rename all videos
  video_rename.py /path/to/videos --recursive

  # Review videos in a browser and add descriptions to their names
  video_rename.py /path/to/videos --interactive

  # See what changes would be made without actually renaming anything
  video_rename.py /path/to/videos --dry-run

  # Process a file with debug output
  video_rename.py my_video.mp4 --debug

  # Process specific files and a directory (non-recursively)
  video_rename.py my_video_1.mp4 my_video_2.mov /path/to/other_vids
""",
    )
    parser.add_argument(
        "paths", nargs="+", help="One or more paths to video files or directories."
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Recursively scan for videos in any specified directories.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print proposed renames but do not modify any files.",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Review videos in a browser and add descriptions to their names.",
    )
    parser.add_argument(
        "--include-described",
        action="store_true",
        help="In interactive mode, also review videos that appear to have descriptions.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug printing for orientation detection.",
    )

    args = parser.parse_args()

    if not EXIFTOOL_PATH:
        print("Error: 'exiftool' is not installed or not in your system's PATH.")
        print("Please install it to use this script.")
        sys.exit(1)

    # Determine base_dir for relative path printing in recursive mode
    base_dir = None
    if args.recursive and len(args.paths) == 1 and Path(args.paths[0]).is_dir():
        # Resolve to an absolute path for consistent relative_to calculations
        base_dir = Path(args.paths[0]).resolve()

    video_files = list(get_video_files(args.paths, args.recursive))

    if not video_files:
        print("No video files found to process.")
        return

    if args.include_described and not args.interactive:
        parser.error("--include-described can only be used with --interactive")

    if args.interactive:
        run_interactive(
            sorted(video_files, key=lambda path: str(path).lower()),
            include_described=args.include_described,
            dry_run=args.dry_run,
            debug=args.debug,
        )
        return

    print(f"Found {len(video_files)} video file(s) to process...")

    for file_path in video_files:
        try:
            # Resolve file_path to absolute for consistent relative_to calculations
            processed_file_path = file_path.resolve()
            process_file(
                processed_file_path, args.dry_run, args.debug, args.recursive, base_dir
            )
        except (
            Exception
        ) as e:  # pylint: disable=broad-exception-caught  # batch guard: log and continue so one bad file doesn't abort the run
            print(
                f"An unexpected error occurred while processing {file_path.name}: {e}"
            )
            if args.debug:
                raise


def run_cli():
    """Run the command-line interface, handling user cancellation cleanly."""
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
