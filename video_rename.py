#!/usr/bin/env python3
"""Rename video files based on GPS location and orientation from EXIF metadata."""

# video_rename.py version 1.0 by Alan Rockefeller
# November 29, 2025

import argparse
import os
import re
import subprocess
import json
import shutil
import sys
from pathlib import Path

try:
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderUnavailable, GeocoderServiceError
except ImportError:
    print(
        "Error: 'geopy' library not found. Please install it with 'pip install geopy'"
    )
    sys.exit(1)

# --- Constants ---

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".hevc", ".mpg", ".mpeg"}

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
GEOCODER = Nominatim(user_agent="video_renamer_cli")
GEOCODE_CACHE = {}


def get_location_info(latitude, longitude):
    """
    Converts latitude and longitude to a location string (Country or USA_State).
    Uses a cache to avoid repeated lookups for the same coordinates.
    Returns None if location cannot be determined.
    """
    if latitude is None or longitude is None:
        return None

    coords = (round(latitude, 4), round(longitude, 4))
    if coords in GEOCODE_CACHE:
        return GEOCODE_CACHE[coords]

    try:
        location = GEOCODER.reverse(coords, language="en", timeout=10)
        if location and "address" in location.raw:
            address = location.raw["address"]
            country = address.get("country", "")
            country_code = address.get("country_code", "").upper()

            if country_code == "US":
                state = address.get("state", "")
                state_abbr = US_STATES.get(
                    state, state
                )  # Fallback to full name if not in dict
                result = f"USA_{state_abbr}"
            else:
                # Replace spaces for filename-friendliness
                result = country.replace(" ", "")

            GEOCODE_CACHE[coords] = result
            return result
    except (GeocoderTimedOut, GeocoderUnavailable, GeocoderServiceError) as e:
        print(f"Warning: Geocoding service error for {coords}: {e}")
        GEOCODE_CACHE[coords] = None
        return None

    GEOCODE_CACHE[coords] = None
    return None


# --- EXIF and File Operations ---


def get_exif_data(file_path):
    """Extracts EXIF data from a file using exiftool."""
    if not EXIFTOOL_PATH:
        print("Warning: exiftool not found. Cannot get EXIF data.")
        return {}
    try:
        result = subprocess.run(
            [EXIFTOOL_PATH, "-json", "-n", "--", str(file_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
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
            for dirpath, _, filenames in os.walk(path, onerror=lambda e: print(
                f"Warning: Cannot access directory: {e}"
            )):
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


_ORIENTATION_RE = re.compile(r"(?:^|[_\- ])(?:horizontal|vertical)(?:$|[_\- ])", re.IGNORECASE)


def _stem_has_orientation(stem):
    """Check whether the stem contains orientation as a distinct token.

    Matches 'horizontal'/'vertical' bounded by start/end of string or common
    filename separators (underscore, hyphen, space).  Does NOT match when the
    word is embedded inside a larger word like 'verticalgarden'.
    """
    return _ORIENTATION_RE.search(stem) is not None


def _build_new_path(file_path, location_str, orientation):
    """Build the new file path with location and orientation appended."""
    stem = file_path.stem
    components = [stem]

    if location_str and not _stem_has_location(stem, location_str):
        components.append(location_str)

    if not _stem_has_orientation(stem):
        components.append(orientation)

    new_stem = "_".join(components)
    return file_path.with_name(new_stem + file_path.suffix)


def _get_display_name(file_path, is_recursive, base_dir):
    """Return a display name: relative path in recursive mode, filename otherwise."""
    if is_recursive and base_dir:
        try:
            return str(file_path.relative_to(base_dir))
        except ValueError:
            pass
    return str(file_path.name)


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

    if dry_run:
        print(f"[DRY] {display_name} → {new_path.name}")
    else:
        if new_path.exists():
            print(f"Warning: Destination file {new_path} already exists. Skipping.")
            return
        try:
            shutil.move(file_path, new_path)
            print(f"[RENAME] {display_name} → {new_path.name}")
        except OSError as e:
            print(f"Error: Failed to rename {file_path.name}. Reason: {e}")


def main():
    """Main function to parse arguments and orchestrate the renaming process."""

    # Custom help message for no-argument case
    if len(sys.argv) == 1:
        print("Usage: video_rename.py [PATH ...] [--recursive] [--dry-run] [--debug]")
        print(
            "\nRenames video files based on GPS location and video orientation from EXIF data."
        )
        print("\nExamples:")
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

    print(f"Found {len(video_files)} video file(s) to process...")

    for file_path in video_files:
        try:
            # Pass new arguments to process_file
            # Resolve file_path to absolute for consistent relative_to calculations in process_file
            processed_file_path = file_path.resolve()
            process_file(
                processed_file_path, args.dry_run, args.debug, args.recursive, base_dir
            )
        except Exception as e:  # pylint: disable=broad-exception-caught  # batch guard: log and continue so one bad file doesn't abort the run
            print(
                f"An unexpected error occurred while processing {file_path.name}: {e}"
            )
            if args.debug:
                raise


if __name__ == "__main__":
    main()
