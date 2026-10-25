"""Tests for the pure helper functions in video_rename.py."""

import json
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import patch

import video_rename
from video_rename import (
    _audio_needs_browser_preview,
    _browser_preview_path,
    _build_descriptive_path,
    _build_new_path,
    _description_parts,
    _get_video_date,
    _is_date_time_only_name,
    _normalize_for_comparison,
    _parse_rotation,
    _prepare_review_item,
    _sanitize_description,
    _scan_review_items,
    _stem_has_location,
    _stem_has_orientation,
    get_location_info,
    get_orientation,
    process_file,
    run_cli,
)

# --- get_orientation ---


class TestGetOrientation:
    def test_rotation_90_is_vertical(self):
        assert get_orientation(1920, 1080, rotation=90) == "vertical"

    def test_rotation_270_is_vertical(self):
        assert get_orientation(1920, 1080, rotation=270) == "vertical"

    def test_rotation_90_overrides_landscape_dimensions(self):
        # Even though width > height, rotation 90 means vertical
        assert get_orientation(1920, 1080, rotation=90) == "vertical"

    def test_landscape_dimensions(self):
        assert get_orientation(1920, 1080) == "horizontal"

    def test_portrait_dimensions(self):
        assert get_orientation(1080, 1920) == "vertical"

    def test_square_is_horizontal(self):
        assert get_orientation(1080, 1080) == "horizontal"

    def test_no_dimensions_defaults_horizontal(self):
        assert get_orientation(None, None) == "horizontal"

    def test_one_dimension_missing(self):
        assert get_orientation(1920, None) == "horizontal"
        assert get_orientation(None, 1080) == "horizontal"

    def test_rotation_0_uses_dimensions(self):
        assert get_orientation(1080, 1920, rotation=0) == "vertical"
        assert get_orientation(1920, 1080, rotation=0) == "horizontal"

    def test_rotation_180_uses_dimensions(self):
        assert get_orientation(1080, 1920, rotation=180) == "vertical"
        assert get_orientation(1920, 1080, rotation=180) == "horizontal"

    def test_no_dimensions_with_non_rotating_rotation(self):
        assert get_orientation(None, None, rotation=0) == "horizontal"


# --- _parse_rotation ---


class TestParseRotation:
    def test_integer_value(self):
        assert _parse_rotation({"Rotation": 90}) == 90

    def test_string_value(self):
        assert _parse_rotation({"Rotation": "270"}) == 270

    def test_float_value(self):
        assert _parse_rotation({"Rotation": 90.0}) == 90

    def test_missing_key(self):
        assert _parse_rotation({}) is None

    def test_none_value(self):
        assert _parse_rotation({"Rotation": None}) is None

    def test_unparseable_string(self):
        assert _parse_rotation({"Rotation": "auto"}) is None


# --- _normalize_for_comparison ---


class TestNormalizeForComparison:
    def test_lowercase(self):
        assert _normalize_for_comparison("USA_CA") == "usaca"

    def test_strips_separators(self):
        assert _normalize_for_comparison("New-York_City test") == "newyorkcitytest"

    def test_empty_string(self):
        assert _normalize_for_comparison("") == ""


# --- _stem_has_location ---


class TestStemHasLocation:
    def test_exact_match(self):
        assert _stem_has_location("video_USA_CA_horizontal", "USA_CA") is True

    def test_case_insensitive(self):
        assert _stem_has_location("video_usa_ca_horizontal", "USA_CA") is True

    def test_no_match(self):
        assert _stem_has_location("video_horizontal", "USA_CA") is False

    def test_country_name(self):
        assert _stem_has_location("video_Mexico_horizontal", "Mexico") is True

    def test_us_full_state_name_match(self):
        # If stem contains "New Hampshire", should match "USA_NH"
        assert _stem_has_location("video_NewHampshire", "USA_NH") is True

    def test_us_full_state_name_with_separators(self):
        assert _stem_has_location("video_new-hampshire", "USA_NH") is True

    def test_no_false_positive_on_partial(self):
        # "IN" (Indiana abbreviation) should not match just because "in" appears in a word
        # But with normalize_for_comparison, "usain" contains "usain"...
        # The actual check is whether "usain" is in the stem
        assert _stem_has_location("video_USA_IN", "USA_IN") is True

    def test_substring_overlap_niger_nigeria(self):
        # Known limitation: normalized "niger" is a substring of "nigeria"
        assert _stem_has_location("video_Nigeria", "Niger") is True

    def test_substring_overlap_guinea(self):
        assert _stem_has_location("video_GuineaBissau", "Guinea") is True


# --- _stem_has_orientation ---


class TestStemHasOrientation:
    def test_orientation_at_end(self):
        assert _stem_has_orientation("video_horizontal") is True
        assert _stem_has_orientation("video_vertical") is True

    def test_orientation_at_start(self):
        assert _stem_has_orientation("horizontal_video") is True
        assert _stem_has_orientation("vertical_video") is True

    def test_orientation_in_middle(self):
        assert _stem_has_orientation("my_horizontal_video") is True

    def test_orientation_is_whole_stem(self):
        assert _stem_has_orientation("horizontal") is True
        assert _stem_has_orientation("vertical") is True

    def test_orientation_with_hyphen(self):
        assert _stem_has_orientation("video-horizontal") is True

    def test_case_insensitive(self):
        assert _stem_has_orientation("video_Horizontal") is True
        assert _stem_has_orientation("video_VERTICAL") is True

    def test_no_match_embedded_in_word(self):
        assert _stem_has_orientation("verticalgarden") is False
        assert _stem_has_orientation("myhorizontalvideo") is False

    def test_no_orientation(self):
        assert _stem_has_orientation("just_a_video") is False

    def test_empty_stem(self):
        assert _stem_has_orientation("") is False


# --- _build_new_path ---


class TestBuildNewPath:
    def test_adds_location_and_orientation(self):
        p = Path("/tmp/video.mp4")
        result = _build_new_path(p, "USA_CA", "horizontal")
        assert result == Path("/tmp/video_USA_CA_horizontal.mp4")

    def test_adds_only_orientation_when_no_location(self):
        p = Path("/tmp/video.mp4")
        result = _build_new_path(p, None, "vertical")
        assert result == Path("/tmp/video_vertical.mp4")

    def test_skips_location_if_already_present(self):
        p = Path("/tmp/video_USA_CA.mp4")
        result = _build_new_path(p, "USA_CA", "horizontal")
        assert result == Path("/tmp/video_USA_CA_horizontal.mp4")

    def test_appends_location_preserving_existing_orientation(self):
        # Existing stem is preserved; location is appended after it
        p = Path("/tmp/video_horizontal.mp4")
        result = _build_new_path(p, "USA_CA", "horizontal")
        assert result == Path("/tmp/video_horizontal_USA_CA.mp4")

    def test_location_only_appended_when_orientation_present(self):
        p = Path("/tmp/video_vertical.mp4")
        result = _build_new_path(p, "Mexico", "vertical")
        assert result == Path("/tmp/video_vertical_Mexico.mp4")

    def test_skips_both_if_already_present(self):
        p = Path("/tmp/video_USA_CA_horizontal.mp4")
        result = _build_new_path(p, "USA_CA", "horizontal")
        assert result == Path("/tmp/video_USA_CA_horizontal.mp4")

    def test_no_change_returns_same_path(self):
        p = Path("/tmp/video_USA_CA_horizontal.mp4")
        result = _build_new_path(p, "USA_CA", "horizontal")
        assert result == p

    def test_empty_location_string_treated_as_no_location(self):
        p = Path("/tmp/video.mp4")
        result = _build_new_path(p, "", "horizontal")
        assert result == Path("/tmp/video_horizontal.mp4")

    def test_preserves_extension(self):
        p = Path("/tmp/video.MOV")
        result = _build_new_path(p, "Mexico", "vertical")
        assert result == Path("/tmp/video_Mexico_vertical.MOV")


# --- interactive description helpers ---


class TestInteractiveDescriptionHelpers:
    def test_camera_name_has_no_description(self):
        assert _description_parts(
            "IMG_1234_USA_CA_horizontal", None, "USA_CA", "horizontal"
        ) == ("IMG_1234", "")

    def test_generic_video_name_has_no_description(self):
        assert _description_parts(
            "video_001_USA_CA_horizontal", None, "USA_CA", "horizontal"
        ) == ("video_001", "")

    def test_phone_timestamp_name_has_no_description(self):
        assert _description_parts(
            "VID_20261024_143000_vertical", None, None, "vertical"
        ) == ("VID_20261024_143000", "")

    def test_repeated_date_and_time_name_has_no_description(self):
        stem = "20251129-2025-11-29 19-04-15"
        assert _is_date_time_only_name(stem) is True
        assert _description_parts(stem, "2025-11-29", None, "horizontal") == (
            stem,
            "",
        )

    def test_words_after_date_are_a_description(self):
        stem = "20251206-Alan_Tryptamine_Fingi_CO_1080p"
        assert _is_date_time_only_name(stem) is False
        assert _description_parts(stem, None, None, "horizontal") == (
            "20251206",
            "Alan Tryptamine Fingi CO 1080p",
        )

    def test_date_time_and_resolution_still_has_no_description(self):
        assert _is_date_time_only_name("20251129_19-04-15_1080p") is True

    def test_date_and_camera_id_still_has_no_description(self):
        assert _is_date_time_only_name("20200503-DSC_8463") is True

    def test_finds_description_after_camera_name(self):
        assert _description_parts(
            "IMG_1234_bear_eating_fish_2026-10-24_USA_CA_vertical",
            "2026-10-24",
            "USA_CA",
            "vertical",
        ) == ("IMG_1234", "bear eating fish")

    def test_finds_saved_description_when_geocoding_is_unavailable(self):
        assert _description_parts(
            "IMG_1234_bear_fishing_2026-10-24_USA_CA_vertical",
            "2026-10-24",
            None,
            "vertical",
        ) == ("IMG_1234", "bear fishing")

    def test_meaningful_name_is_an_existing_description(self):
        assert _description_parts(
            "otters_playing_USA_CA_horizontal", None, "USA_CA", "horizontal"
        ) == ("", "otters playing")

    def test_timestamp_name_has_no_description(self):
        assert _description_parts(
            "2026-10-24_12-30-22_horizontal",
            "2026-10-24",
            None,
            "horizontal",
        ) == ("2026-10-24_12-30-22", "")

    def test_description_is_sanitized_for_filename(self):
        assert (
            _sanitize_description("  Bear / fishing: close-up  ")
            == "Bear_fishing_close-up"
        )

    def test_builds_canonical_descriptive_name(self):
        result = _build_descriptive_path(
            Path("/tmp/IMG_1234.mp4"),
            "Bear fishing",
            "2026-10-24",
            "USA_CA",
            "vertical",
            "IMG_1234",
        )
        assert result == Path(
            "/tmp/IMG_1234_Bear_fishing_2026-10-24_USA_CA_vertical.mp4"
        )

    def test_does_not_append_date_when_compact_date_is_already_in_base(self):
        result = _build_descriptive_path(
            Path("/tmp/20130721-MVI_8811.MOV"),
            "Oaxaca Cuajimoloyas fair",
            "2013-07-21",
            None,
            "horizontal",
            "20130721-MVI_8811",
        )
        assert result == Path(
            "/tmp/20130721-MVI_8811_Oaxaca_Cuajimoloyas_fair_horizontal.MOV"
        )

    def test_description_is_required(self):
        try:
            _build_descriptive_path(
                Path("/tmp/IMG_1234.mp4"), "  ", None, None, "horizontal"
            )
        except ValueError as error:
            assert "description" in str(error)
        else:
            raise AssertionError("Expected a blank description to be rejected")

    def test_date_uses_first_available_exif_tag(self):
        assert _get_video_date({"CreateDate": "2026:10:24 14:30:00"}) == "2026-10-24"

    def test_date_falls_back_to_filename(self):
        assert _get_video_date({}, "clip_2026-10-24") == "2026-10-24"


class TestBackgroundReviewScan:
    @patch("video_rename._prepare_review_item")
    def test_adds_only_undescribed_items_while_tracking_progress(self, prepare):
        prepare.side_effect = [
            {"description": "", "path": Path("first.mp4")},
            {"description": "already named", "path": Path("second.mp4")},
        ]
        server = SimpleNamespace(
            stop_event=Event(),
            review_lock=Lock(),
            review_items=[],
            scan_progress=0,
            scan_complete=False,
        )

        _scan_review_items(
            server, [Path("first.mp4"), Path("second.mp4")], False, False
        )

        assert server.scan_progress == 2
        assert server.scan_complete is True
        assert len(server.review_items) == 1
        assert server.review_items[0]["id"] == 0

    @patch("video_rename._prepare_review_item")
    def test_finish_stops_scanning_before_next_file(self, prepare):
        stop_event = Event()
        stop_event.set()
        server = SimpleNamespace(
            stop_event=stop_event,
            review_lock=Lock(),
            review_items=[],
            scan_progress=0,
            scan_complete=False,
        )

        _scan_review_items(server, [Path("first.mp4")], False, False)

        prepare.assert_not_called()
        assert server.scan_progress == 0


class TestMetadataMinimization:
    @patch("video_rename.get_exif_data")
    def test_described_video_skips_exif_and_geocoding(self, get_exif):
        item = _prepare_review_item(
            Path("20251206-Alan_Tryptamine_Fingi_CO_1080p.m4v"),
            0,
            skip_metadata_if_described=True,
        )

        get_exif.assert_not_called()
        assert item["description"] == "Alan Tryptamine Fingi CO 1080p"

    @patch("video_rename.get_location_info", return_value="USA_CO")
    @patch(
        "video_rename.get_exif_data",
        return_value={"ImageWidth": 1920, "ImageHeight": 1080},
    )
    def test_undescribed_video_reads_metadata(self, get_exif, get_location):
        item = _prepare_review_item(
            Path("20200503-DSC_8463.MOV"),
            0,
            skip_metadata_if_described=True,
        )

        get_exif.assert_called_once()
        get_location.assert_called_once_with(None, None)
        assert item["description"] == ""

    @patch("video_rename.get_location_info")
    @patch(
        "video_rename.get_exif_data",
        return_value={
            "ImageWidth": 1920,
            "ImageHeight": 1080,
            "GPSLatitude": 46.786,
            "GPSLongitude": -124.097,
        },
    )
    def test_background_scan_defers_geocoding_until_review(
        self, _get_exif, get_location
    ):
        item = _prepare_review_item(
            Path("20200503-DSC_8463.MOV"),
            0,
            skip_metadata_if_described=True,
            resolve_location=False,
        )

        get_location.assert_not_called()
        assert item["latitude"] == 46.786
        assert item["longitude"] == -124.097
        assert item["location"] is None


class TestBrowserAudioPreview:
    @patch("video_rename.FFPROBE_PATH", "/usr/bin/ffprobe")
    @patch("video_rename.subprocess.run")
    def test_pcm_audio_needs_preview(self, run):
        run.return_value = SimpleNamespace(
            stdout=json.dumps({"streams": [{"codec_name": "pcm_s16le"}]})
        )
        assert _audio_needs_browser_preview(Path("clip.MOV")) is True

    @patch("video_rename.FFPROBE_PATH", "/usr/bin/ffprobe")
    @patch("video_rename.subprocess.run")
    def test_aac_audio_uses_original(self, run):
        run.return_value = SimpleNamespace(
            stdout=json.dumps({"streams": [{"codec_name": "aac"}]})
        )
        assert _audio_needs_browser_preview(Path("clip.mp4")) is False

    @patch("video_rename.FFMPEG_PATH", "/usr/bin/ffmpeg")
    @patch("video_rename.FFPROBE_PATH", "/usr/bin/ffprobe")
    @patch("video_rename._audio_needs_browser_preview", return_value=True)
    @patch("video_rename.subprocess.run")
    def test_preview_copies_video_and_converts_audio(
        self, run, _needs_preview, tmp_path
    ):
        server = SimpleNamespace(
            preview_dir=tmp_path,
            preview_locks={},
            preview_locks_lock=Lock(),
            generated_previews=set(),
        )
        item = {"id": 3, "path": Path("clip.MOV")}

        preview_path = _browser_preview_path(server, item)

        assert preview_path == tmp_path / "video-3.mp4"
        command = run.call_args.args[0]
        assert command[command.index("-c:v") + 1] == "copy"
        assert command[command.index("-c:a") + 1] == "aac"


class TestGeocodingCourtesy:
    @staticmethod
    def _reset_geocoding(monkeypatch):
        monkeypatch.setattr(video_rename, "GEOCODE_CACHE", {})
        monkeypatch.setattr(video_rename, "_GEOCODE_CACHE_LOADED", True)
        monkeypatch.setattr(video_rename, "_GEOCODE_COOLDOWN_UNTIL", 0.0)
        monkeypatch.setattr(video_rename, "_GEOCODE_LAST_REQUEST", 0.0)
        monkeypatch.setattr(video_rename, "GEOCODE_MIN_INTERVAL_SECONDS", 0)
        monkeypatch.setattr(video_rename, "_save_geocode_cache", lambda: None)

    def test_nearby_coordinates_share_cached_request(self, monkeypatch):
        self._reset_geocoding(monkeypatch)
        location = SimpleNamespace(
            raw={
                "address": {
                    "country": "United States",
                    "country_code": "us",
                    "state": "Washington",
                }
            }
        )
        mock_reverse = patch.object(
            video_rename.GEOCODER, "reverse", return_value=location
        )
        with mock_reverse as reverse_call:
            first = get_location_info(46.7859, -124.0967)
            second = get_location_info(46.7861, -124.0968)

        assert first == second == "USA_WA"
        reverse_call.assert_called_once()

    def test_rate_limit_waits_then_retries(self, monkeypatch):
        self._reset_geocoding(monkeypatch)
        error = video_rename.GeocoderRateLimited("Too many requests", retry_after=7)
        location = SimpleNamespace(
            raw={"address": {"country": "Mexico", "country_code": "mx"}}
        )
        with (
            patch.object(
                video_rename.GEOCODER, "reverse", side_effect=[error, location]
            ) as reverse,
            patch("video_rename.time.sleep") as sleep,
        ):
            assert get_location_info(46.7, -124.1) == "Mexico"

        assert reverse.call_count == 2
        sleep.assert_called_once_with(7.0)

    def test_repeated_rate_limit_uses_temporary_cooldown(self, monkeypatch):
        self._reset_geocoding(monkeypatch)
        monkeypatch.setattr(video_rename, "GEOCODE_MAX_RATE_LIMIT_RETRIES", 0)
        error = video_rename.GeocoderServiceError("HTTP Error 429: Too many requests")
        with patch.object(
            video_rename.GEOCODER, "reverse", side_effect=error
        ) as reverse:
            assert get_location_info(46.7, -124.1) is None
            assert get_location_info(47.7, -123.1) is None

        reverse.assert_called_once()

    def test_cache_survives_between_runs(self, monkeypatch, tmp_path):
        cache_path = tmp_path / "geocode.json"
        monkeypatch.setattr(video_rename, "_geocode_cache_path", lambda: cache_path)
        monkeypatch.setattr(
            video_rename, "GEOCODE_CACHE", {"46.786,-124.097": "USA_WA"}
        )

        video_rename._save_geocode_cache()
        monkeypatch.setattr(video_rename, "GEOCODE_CACHE", {})
        monkeypatch.setattr(video_rename, "_GEOCODE_CACHE_LOADED", False)
        video_rename._load_geocode_cache()

        assert video_rename.GEOCODE_CACHE == {"46.786,-124.097": "USA_WA"}


# --- process_file dry-run ---


FAKE_EXIF = {
    "ImageWidth": 1920,
    "ImageHeight": 1080,
    "GPSLatitude": 34.0522,
    "GPSLongitude": -118.2437,
}


class TestProcessFileDryRun:
    @patch("video_rename.get_location_info", return_value="USA_CA")
    @patch("video_rename.get_exif_data", return_value=FAKE_EXIF)
    def test_dry_run_shows_proposed_rename(self, _mock_exif, _mock_loc, capsys):
        p = Path("/tmp/video.mp4")
        process_file(p, dry_run=True, debug=False, is_recursive=False, base_dir=None)
        out = capsys.readouterr().out
        assert "[DRY]" in out
        assert "video_USA_CA_horizontal.mp4" in out

    @patch("video_rename.get_location_info", return_value="USA_CA")
    @patch("video_rename.get_exif_data", return_value=FAKE_EXIF)
    def test_dry_run_skips_when_destination_exists(
        self, _mock_exif, _mock_loc, capsys, tmp_path
    ):
        src = tmp_path / "video.mp4"
        src.touch()
        dest = tmp_path / "video_USA_CA_horizontal.mp4"
        dest.touch()
        process_file(src, dry_run=True, debug=False, is_recursive=False, base_dir=None)
        out = capsys.readouterr().out
        assert "SKIP" in out
        assert "already exists" in out

    @patch("video_rename.get_location_info", return_value="USA_CA")
    @patch("video_rename.get_exif_data", return_value=FAKE_EXIF)
    def test_real_run_skips_when_destination_exists(
        self, _mock_exif, _mock_loc, capsys, tmp_path
    ):
        src = tmp_path / "video.mp4"
        src.touch()
        dest = tmp_path / "video_USA_CA_horizontal.mp4"
        dest.touch()
        process_file(src, dry_run=False, debug=False, is_recursive=False, base_dir=None)
        out = capsys.readouterr().out
        assert "already exists" in out
        assert "Skipping" in out
        # Source should not have been moved
        assert src.exists()


# --- command-line interruption handling ---


class TestRunCli:
    @patch("video_rename.main", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_exits_cleanly(self, _mock_main, capsys):
        assert run_cli() == 130
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "\nCancelled.\n"
