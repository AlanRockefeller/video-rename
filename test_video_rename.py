"""Tests for the pure helper functions in video_rename.py."""

import json
import os
import subprocess
import sys
from email.message import Message
from io import BytesIO
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import video_rename
from video_rename import (
    _INTERACTIVE_HTML,
    _audio_needs_browser_preview,
    _browser_preview_path,
    _build_descriptive_path,
    _build_new_path,
    _delete_review_item,
    _description_parts,
    _get_video_date,
    _is_date_time_only_name,
    _location_from_geocoder_result,
    _normalize_for_comparison,
    _orientation_from_stem,
    _parse_rotation,
    _prepare_review_item,
    _review_items_response,
    _ReviewRequestHandler,
    _sanitize_description,
    _scan_review_items,
    _stem_has_location,
    _stem_has_orientation,
    _stop_preview_conversions,
    get_location_info,
    get_orientation,
    get_video_files,
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

    def test_adjacent_orientation_tokens_both_match(self):
        assert _stem_has_orientation("vertical_horizontal") is True


# --- _orientation_from_stem ---


class TestOrientationFromStem:
    def test_trailing_token_wins(self):
        assert _orientation_from_stem("vertical_then_horizontal") == "horizontal"
        assert (
            _orientation_from_stem("IMG_1_sunset_horizontal_pan_USA_CA_vertical")
            == "vertical"
        )

    def test_case_is_normalized(self):
        assert _orientation_from_stem("clip_Vertical") == "vertical"

    def test_no_orientation(self):
        assert _orientation_from_stem("clip") is None
        assert _orientation_from_stem("verticalgarden") is None


# --- get_video_files ---


class TestGetVideoFiles:
    def test_duplicate_paths_are_listed_once(self, tmp_path):
        video = tmp_path / "a.mp4"
        video.write_bytes(b"")
        (tmp_path / "b.mov").write_bytes(b"")

        files = list(get_video_files([str(tmp_path), str(video), str(video)], False))

        assert sorted(path.name for path in files) == ["a.mp4", "b.mov"]


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

    def test_longest_camera_prefix_keeps_counter_with_camera_name(self):
        assert _description_parts("video_001_bear_fishing") == (
            "video_001",
            "bear fishing",
        )
        assert _description_parts("IMG_1234_5678_bear") == ("IMG_1234_5678", "bear")

    def test_date_and_camera_id_prefix_is_recognized(self):
        assert _description_parts("20200503-DSC_8463_bear_fishing") == (
            "20200503-DSC_8463",
            "bear fishing",
        )

    def test_single_word_after_timestamp_is_split_from_it(self):
        assert _description_parts(
            "2026-10-24_12-30-22_Mexico_horizontal", "2026-10-24", None, "horizontal"
        ) == ("2026-10-24_12-30-22", "Mexico")

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

    def test_invalid_exif_date_falls_through_to_valid_tag(self):
        exif = {
            "DateTimeOriginal": "0000:00:00 00:00:00",
            "CreateDate": "2026:10:24 14:30:00",
        }
        assert _get_video_date(exif) == "2026-10-24"

    def test_invalid_exif_and_filename_dates_are_ignored(self):
        assert _get_video_date({"CreateDate": "2026:02:30"}, "clip_2026-13-01") is None


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

    @patch("video_rename.get_location_info", return_value="Mexico")
    @patch(
        "video_rename.get_exif_data",
        return_value={
            "ImageWidth": 1920,
            "ImageHeight": 1080,
            "GPSLatitude": 19.4,
            "GPSLongitude": -99.1,
        },
    )
    def test_single_country_token_after_camera_name_is_not_a_description(
        self, _get_exif, get_location
    ):
        item = _prepare_review_item(
            Path("IMG_1234_Mexico_horizontal.mp4"),
            0,
            skip_metadata_if_described=True,
            resolve_location=False,
        )

        get_location.assert_called_once_with(19.4, -99.1)
        assert item["base_stem"] == "IMG_1234"
        assert item["description"] == ""
        assert item["location"] == "Mexico"

    @patch("video_rename.get_location_info", return_value="Mexico")
    @patch(
        "video_rename.get_exif_data",
        return_value={
            "ImageWidth": 1920,
            "ImageHeight": 1080,
            "GPSLatitude": 19.4,
            "GPSLongitude": -99.1,
        },
    )
    def test_single_country_token_after_any_camera_style_name_is_checked(
        self, _get_exif, get_location
    ):
        for name in (
            "PXL_20261024_143000123_Mexico_horizontal.mp4",
            "video_001_Mexico_horizontal.mp4",
            "2026-10-24_12-30-22_Mexico_horizontal.mp4",
        ):
            get_location.reset_mock()
            item = _prepare_review_item(
                Path(name), 0, skip_metadata_if_described=True, resolve_location=False
            )

            get_location.assert_called_once_with(19.4, -99.1)
            assert item["description"] == "", name
            assert item["location"] == "Mexico"

    @patch("video_rename.get_location_info", return_value=None)
    @patch(
        "video_rename.get_exif_data",
        return_value={
            "ImageWidth": 1920,
            "ImageHeight": 1080,
            "GPSLatitude": 19.4,
            "GPSLongitude": -99.1,
        },
    )
    def test_unverified_single_token_stays_in_review(self, _get_exif, _get_location):
        item = _prepare_review_item(
            Path("IMG_1234_Mexico_horizontal.mp4"),
            0,
            skip_metadata_if_described=True,
            resolve_location=False,
        )

        assert item["description"] == "Mexico"
        assert item["needs_review"] is True

        server = SimpleNamespace(
            stop_event=Event(),
            review_lock=Lock(),
            review_items=[],
            scan_progress=0,
            scan_complete=False,
        )
        with patch("video_rename._prepare_review_item", return_value=item):
            _scan_review_items(server, [item["path"]], False, False)

        assert len(server.review_items) == 1

    @patch("video_rename.get_location_info", return_value="Mexico")
    @patch(
        "video_rename.get_exif_data",
        return_value={
            "ImageWidth": 1920,
            "ImageHeight": 1080,
            "GPSLatitude": 19.4,
            "GPSLongitude": -99.1,
        },
    )
    def test_genuine_single_word_description_is_preserved(
        self, _get_exif, _get_location
    ):
        item = _prepare_review_item(
            Path("IMG_1234_Beach_horizontal.mp4"),
            0,
            skip_metadata_if_described=True,
            resolve_location=False,
        )

        assert item["description"] == "Beach"


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

    @staticmethod
    def _server(tmp_path):
        return SimpleNamespace(
            preview_dir=tmp_path,
            preview_locks={},
            preview_locks_lock=Lock(),
            preview_processes=set(),
            generated_previews=set(),
            stop_event=Event(),
        )

    @staticmethod
    def _ffmpeg_process(returncode=0):
        process = MagicMock()
        process.communicate.return_value = ("", "")
        process.returncode = returncode
        return process

    @patch("video_rename.FFMPEG_PATH", "/usr/bin/ffmpeg")
    @patch("video_rename.FFPROBE_PATH", "/usr/bin/ffprobe")
    @patch("video_rename._audio_needs_browser_preview", return_value=True)
    @patch("video_rename.subprocess.Popen")
    def test_preview_copies_video_and_converts_audio(
        self, popen, _needs_preview, tmp_path
    ):
        popen.return_value = self._ffmpeg_process()
        server = self._server(tmp_path)
        item = {"id": 3, "path": Path("clip.MOV")}

        preview_path = _browser_preview_path(server, item)

        assert preview_path == tmp_path / "video-3.mp4"
        command = popen.call_args.args[0]
        assert command[command.index("-c:v") + 1] == "copy"
        assert command[command.index("-c:a") + 1] == "aac"
        popen.return_value.communicate.assert_called_once_with(
            timeout=video_rename.FFMPEG_PREVIEW_TIMEOUT_SECONDS
        )
        assert server.preview_processes == set()

    @patch("video_rename.FFMPEG_PATH", "/usr/bin/ffmpeg")
    @patch("video_rename.FFPROBE_PATH", "/usr/bin/ffprobe")
    @patch("video_rename._audio_needs_browser_preview")
    @patch("video_rename.subprocess.Popen")
    def test_evicted_audio_preview_is_regenerated(self, popen, needs_preview, tmp_path):
        popen.return_value = self._ffmpeg_process()
        server = self._server(tmp_path)
        item = {
            "id": 4,
            "path": Path("pcm-clip.MOV"),
            "browser_preview_checked": True,
            "browser_preview_path": tmp_path / "missing-preview.mp4",
        }

        assert _browser_preview_path(server, item) == tmp_path / "video-4.mp4"

        needs_preview.assert_not_called()
        popen.assert_called_once()

    @patch("video_rename.FFMPEG_PATH", "/usr/bin/ffmpeg")
    @patch("video_rename.FFPROBE_PATH", "/usr/bin/ffprobe")
    @patch("video_rename._audio_needs_browser_preview", return_value=True)
    @patch("video_rename.subprocess.Popen")
    def test_stalled_conversion_is_killed_and_original_is_served(
        self, popen, _needs_preview, tmp_path, capsys
    ):
        process = self._ffmpeg_process()
        process.communicate.side_effect = [
            subprocess.TimeoutExpired("ffmpeg", 300),
            ("", ""),
        ]
        popen.return_value = process
        server = self._server(tmp_path)
        partial_preview = tmp_path / "video-5.mp4"
        partial_preview.write_bytes(b"partial")
        item = {"id": 5, "path": Path("slow.MOV")}

        assert _browser_preview_path(server, item) == Path("slow.MOV")

        process.kill.assert_called_once()
        assert server.preview_processes == set()
        assert not partial_preview.exists()
        assert "Could not create browser audio preview" in capsys.readouterr().out

    def test_finishing_terminates_running_conversions(self, tmp_path):
        process = MagicMock()
        process.wait.side_effect = [subprocess.TimeoutExpired("ffmpeg", 5), None]
        server = self._server(tmp_path)
        server.preview_processes.add(process)

        _stop_preview_conversions(server)

        process.terminate.assert_called_once()
        process.kill.assert_called_once()


class TestInteractiveDelete:
    @staticmethod
    def _server(dry_run):
        return SimpleNamespace(
            dry_run=dry_run,
            preview_locks={},
            preview_locks_lock=Lock(),
            generated_previews=set(),
            rename_lock=Lock(),
            review_lock=Lock(),
        )

    def test_delete_moves_video_to_trash(self, tmp_path, fake_trash):
        video = tmp_path / "delete-me.mp4"
        video.write_bytes(b"video")
        item = {"id": 0, "path": video}

        assert _delete_review_item(self._server(False), item) == video

        assert not video.exists()
        assert (fake_trash / "delete-me.mp4").read_bytes() == b"video"
        assert item["deleted"] is True

    def test_delete_keeps_video_when_no_trash_is_available(self, tmp_path, monkeypatch):
        video = tmp_path / "keep-me.mp4"
        video.write_bytes(b"video")
        item = {"id": 0, "path": video}

        def no_trash(_path):
            raise video_rename.TrashUnavailableError("No Trash is available")

        monkeypatch.setattr(video_rename, "move_to_trash", no_trash)

        with pytest.raises(ValueError, match="No Trash"):
            _delete_review_item(self._server(False), item)

        assert video.exists()
        assert not item.get("deleted")

    def test_dry_run_keeps_video(self, tmp_path):
        video = tmp_path / "keep-me.mp4"
        video.write_bytes(b"video")
        item = {"id": 0, "path": video}

        _delete_review_item(self._server(True), item)

        assert video.exists()
        assert item["deleted"] is True

    def test_interface_requires_explicit_confirmation(self):
        assert "window.confirm(prompt)" in _INTERACTIVE_HTML
        assert "to the Trash?" in _INTERACTIVE_HTML
        assert "cannot be undone" not in _INTERACTIVE_HTML


class TestInteractiveServerHardening:
    @staticmethod
    def _review_item(item_id, deleted=False):
        return {
            "id": item_id,
            "path": Path(f"video-{item_id}.mp4"),
            "base_stem": f"video-{item_id}",
            "description": "",
            "date": None,
            "location": None,
            "orientation": "horizontal",
            "latitude": None,
            "longitude": None,
            "deleted": deleted,
        }

    def test_review_items_response_is_incremental(self):
        server = SimpleNamespace(
            review_lock=Lock(),
            review_items=[
                self._review_item(0),
                self._review_item(1, deleted=True),
                self._review_item(2),
            ],
            scan_progress=3,
            scan_total=3,
            scan_complete=True,
            dry_run=False,
        )

        response = _review_items_response(server, 1)

        assert [item["id"] for item in response["items"]] == [2]
        assert response["next_offset"] == 3
        assert "?since=${itemOffset}" in _INTERACTIVE_HTML

    @staticmethod
    def _request_handler(host, content_type=None):
        handler = object.__new__(_ReviewRequestHandler)
        handler.server = SimpleNamespace(server_address=("127.0.0.1", 4321))
        handler.headers = Message()
        handler.headers["Host"] = host
        if content_type:
            handler.headers["Content-Type"] = content_type
        handler.send_error = MagicMock()
        return handler

    def test_accepts_local_json_request(self):
        handler = self._request_handler("127.0.0.1:4321", "application/json")
        assert handler._allow_request(require_json=True) is True
        handler.send_error.assert_not_called()

    def test_rejects_nonlocal_host(self):
        handler = self._request_handler("attacker.example:4321", "application/json")
        assert handler._allow_request(require_json=True) is False
        handler.send_error.assert_called_once_with(403, "Local requests only")

    def test_rejects_simple_cross_origin_content_type(self):
        handler = self._request_handler("localhost:4321", "text/plain")
        assert handler._allow_request(require_json=True) is False
        handler.send_error.assert_called_once_with(415, "JSON content type required")

    def test_rejects_negative_content_length(self):
        handler = self._request_handler("localhost:4321", "application/json")
        handler.headers["Content-Length"] = "-1"
        handler.rfile = BytesIO(b"{}")

        try:
            handler._read_json()
        except ValueError as error:
            assert str(error) == "Invalid request length."
        else:
            raise AssertionError("Expected a negative Content-Length to be rejected")


class TestVideoStreaming:
    @staticmethod
    def _handler(range_header=None):
        handler = object.__new__(_ReviewRequestHandler)
        handler.headers = Message()
        if range_header:
            handler.headers["Range"] = range_header
        handler.wfile = BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.send_error = MagicMock()
        return handler

    def test_empty_file_has_zero_content_length(self, tmp_path):
        video = tmp_path / "empty.mp4"
        video.write_bytes(b"")
        handler = self._handler()

        handler._serve_video(video)

        handler.send_response.assert_called_once_with(200)
        handler.send_header.assert_any_call("Content-Length", "0")
        assert handler.wfile.getvalue() == b""

    def test_missing_file_is_reported_as_not_found(self, tmp_path):
        handler = self._handler()

        handler._serve_video(tmp_path / "gone.mp4")

        handler.send_error.assert_called_once_with(404, "Video not found")
        handler.send_response.assert_not_called()

    def test_range_request_streams_requested_bytes(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"0123456789")
        handler = self._handler("bytes=2-5")

        handler._serve_video(video)

        handler.send_response.assert_called_once_with(206)
        handler.send_header.assert_any_call("Content-Range", "bytes 2-5/10")
        assert handler.wfile.getvalue() == b"2345"


class TestInteractiveBrowserLogic:
    def test_skip_cannot_move_past_pending_items(self):
        assert "if (busy || position >= items.length) return;\n  position++;" in (
            _INTERACTIVE_HTML
        )

    def test_location_lookup_waits_for_a_settled_video(self):
        assert "scheduleLocationLookup(item);" in _INTERACTIVE_HTML
        assert "\n  ensureLocation(item);\n" not in _INTERACTIVE_HTML

    def test_corrected_description_replaces_untouched_input(self):
        assert "if (input.value === previousDescription)" in _INTERACTIVE_HTML
        assert "await ensureLocation(item);" in _INTERACTIVE_HTML


class TestMainArguments:
    @patch("video_rename.get_video_files")
    def test_include_described_requires_interactive_before_scanning(
        self, get_files, capsys
    ):
        argv = ["video_rename.py", "/videos", "--include-described"]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exit_info:
            video_rename.main()

        assert exit_info.value.code == 2
        get_files.assert_not_called()
        assert "--include-described can only be used with --interactive" in (
            capsys.readouterr().err
        )


class TestInteractiveRename:
    @staticmethod
    def _handler(dry_run=False):
        handler = object.__new__(_ReviewRequestHandler)
        handler.server = SimpleNamespace(
            rename_lock=Lock(), review_lock=Lock(), dry_run=dry_run
        )
        handler._send_json = MagicMock()
        return handler

    @staticmethod
    def _item(path):
        return {
            "id": 0,
            "path": path,
            "base_stem": "IMG_1234",
            "description": "beach",
            "date": None,
            "location": None,
            "orientation": "horizontal",
            "latitude": None,
            "longitude": None,
        }

    def test_rejects_collision_with_a_different_file(self, tmp_path):
        # The names differ by more than letter case so the files are distinct
        # on case-insensitive filesystems too.
        old = tmp_path / "IMG_1234_sunset_horizontal.mp4"
        old.write_bytes(b"a")
        other = tmp_path / "IMG_1234_Beach_horizontal.mp4"
        other.write_bytes(b"b")

        with pytest.raises(ValueError, match="already exists"):
            self._handler()._rename(self._item(old), "Beach")

        assert old.read_bytes() == b"a"
        assert other.read_bytes() == b"b"

    def test_capitalization_change_is_not_a_collision_with_itself(self, tmp_path):
        old = tmp_path / "IMG_1234_beach_horizontal.mp4"
        old.write_bytes(b"a")
        new = tmp_path / "IMG_1234_Beach_horizontal.mp4"
        # On a case-insensitive filesystem the destination already is the
        # source; elsewhere a hard link mirrors that situation.
        if not new.exists():
            os.link(old, new)
        handler = self._handler()
        item = self._item(old)

        handler._rename(item, "Beach")

        assert item["path"] == new
        assert new.read_bytes() == b"a"
        payload = handler._send_json.call_args.args[0]
        assert payload["item"]["current_name"] == new.name


class TestDeferredGeocodeEndpoint:
    @staticmethod
    def _handler():
        handler = object.__new__(_ReviewRequestHandler)
        handler.server = SimpleNamespace(review_lock=Lock())
        handler._send_json = MagicMock()
        return handler

    @staticmethod
    def _item():
        return {
            "id": 0,
            "path": Path("IMG_1234_Mexico_horizontal.mp4"),
            "base_stem": "IMG_1234",
            "description": "Mexico",
            "date": None,
            "location": None,
            "orientation": "horizontal",
            "latitude": 19.4,
            "longitude": -99.1,
        }

    @patch("video_rename._is_location_cached", return_value=False)
    @patch("video_rename.get_location_info", return_value=None)
    def test_unavailable_lookup_is_not_final(self, _lookup, _cached):
        handler = self._handler()

        handler._geocode(self._item())

        payload = handler._send_json.call_args.args[0]
        assert payload["definitive"] is False
        assert payload["item"]["description"] == "Mexico"

    @patch("video_rename._is_location_cached", return_value=True)
    @patch("video_rename.get_location_info", return_value=None)
    def test_cached_missing_location_is_final(self, _lookup, _cached):
        handler = self._handler()

        handler._geocode(self._item())

        assert handler._send_json.call_args.args[0]["definitive"] is True

    @patch("video_rename.get_location_info", return_value="Mexico")
    def test_found_location_is_removed_from_description(self, _lookup):
        handler = self._handler()

        handler._geocode(self._item())

        payload = handler._send_json.call_args.args[0]
        assert payload["definitive"] is True
        assert payload["item"]["location"] == "Mexico"
        assert payload["item"]["description"] == ""

    def test_browser_retries_an_unfinished_lookup(self):
        assert "item.locationResolved = result.definitive !== false;" in (
            _INTERACTIVE_HTML
        )
        assert "if (!item.locationResolved) item.locationPromise = null;" in (
            _INTERACTIVE_HTML
        )


class TestGeocodingCourtesy:
    @staticmethod
    def _reset_geocoding(monkeypatch):
        monkeypatch.setattr(video_rename, "GEOCODE_CACHE", {})
        monkeypatch.setattr(video_rename, "_GEOCODE_CACHE_LOADED", True)
        monkeypatch.setattr(video_rename, "_GEOCODE_COOLDOWN_UNTIL", 0.0)
        monkeypatch.setattr(video_rename, "_GEOCODE_LAST_REQUEST", 0.0)
        monkeypatch.setattr(video_rename, "_GEOCODE_CONSECUTIVE_SERVICE_ERRORS", 0)
        monkeypatch.setattr(video_rename, "GEOCODE_MIN_INTERVAL_SECONDS", 0)
        monkeypatch.setattr(video_rename, "_save_geocode_cache", lambda: None)

    @staticmethod
    def _result(address):
        return SimpleNamespace(raw={"address": address})

    def test_us_result_without_state_uses_country_token(self):
        result = self._result({"country": "United States", "country_code": "us"})
        assert _location_from_geocoder_result(result) == "USA"

    def test_unlisted_us_state_has_no_spaces(self):
        result = self._result(
            {"country": "United States", "country_code": "us", "state": "Baker Island"}
        )
        assert _location_from_geocoder_result(result) == "USA_BakerIsland"

    def test_result_without_country_is_no_location(self):
        assert _location_from_geocoder_result(self._result({})) is None

    def test_is_location_cached_uses_rounded_key(self, monkeypatch):
        monkeypatch.setattr(video_rename, "GEOCODE_CACHE", {"46.786,-124.097": None})
        monkeypatch.setattr(video_rename, "_GEOCODE_CACHE_LOADED", True)

        assert video_rename._is_location_cached(46.7859, -124.0967) is True
        assert video_rename._is_location_cached(47.0, -124.0) is False
        assert video_rename._is_location_cached(None, -124.0) is False

    def test_repeated_service_errors_pause_lookups(self, monkeypatch):
        self._reset_geocoding(monkeypatch)
        error = video_rename.GeocoderUnavailable("Service not known")
        with patch.object(
            video_rename.GEOCODER, "reverse", side_effect=error
        ) as reverse:
            assert get_location_info(46.7, -124.1) is None
            assert get_location_info(47.7, -123.1) is None
            assert get_location_info(48.7, -122.1) is None

        assert reverse.call_count == 2

    def test_successful_lookup_resets_service_error_count(self, monkeypatch):
        self._reset_geocoding(monkeypatch)
        error = video_rename.GeocoderTimedOut("Timed out")
        location = self._result({"country": "Mexico", "country_code": "mx"})
        with patch.object(
            video_rename.GEOCODER,
            "reverse",
            side_effect=[error, location, error, error],
        ) as reverse:
            assert get_location_info(46.7, -124.1) is None
            assert get_location_info(47.7, -123.1) == "Mexico"
            assert get_location_info(48.7, -122.1) is None
            assert get_location_info(49.7, -121.1) is None

        assert reverse.call_count == 4

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


# --- Transcript-based description suggestions ---


class TestSuggestDescription:
    def test_species_name_comes_first(self):
        transcript = (
            "Here we have a lobster mushroom. This lobster mushroom is "
            "parasitized by Hypomyces lactifluorum, turning it bright orange."
        )

        suggestion = video_rename.suggest_description(transcript)

        assert suggestion.startswith("Hypomyces lactifluorum")
        assert "lobster" in suggestion and "mushroom" in suggestion

    def test_keywords_keep_spoken_order(self):
        transcript = "Bioluminescent fungi glowing tonight. Fungi everywhere, glowing."

        assert video_rename.suggest_description(transcript) == (
            "bioluminescent fungi glowing tonight everywhere"
        )

    def test_common_words_are_not_species_names(self):
        suggestion = video_rename.suggest_description("This area has many puffballs")

        assert not suggestion.startswith("This")
        assert "puffballs" in suggestion

    def test_respects_word_limit(self):
        transcript = "one two three alpha bravo charlie delta echo foxtrot golf"

        assert len(video_rename.suggest_description(transcript, 3).split()) == 3

    def test_nothing_said_gives_no_suggestion(self):
        assert video_rename.suggest_description("") == ""
        assert video_rename.suggest_description(None) == ""
        assert video_rename.suggest_description("oh wow yeah okay") == ""


class TestTranscriber:
    @pytest.fixture(autouse=True)
    def _isolated_cache(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    @staticmethod
    def _video(tmp_path, name="IMG_0001.mp4", content=b"video bytes"):
        path = tmp_path / name
        path.write_bytes(content)
        return path

    def test_cached_transcript_survives_rename(self, tmp_path):
        backend = MagicMock(return_value="  Amanita   muscaria under pines ")
        transcriber = video_rename.Transcriber("base", backend=backend)
        video = self._video(tmp_path)

        with patch.object(
            video_rename.Transcriber, "_extract_audio", return_value=True
        ):
            first = transcriber.transcript(video)
            renamed = video.rename(tmp_path / "IMG_0001_amanita_horizontal.mp4")
            # A new process reads the cache from disk.
            second = video_rename.Transcriber("base", backend=backend).transcript(
                renamed
            )

        assert first == second == "Amanita muscaria under pines"
        backend.assert_called_once()

    def test_cache_is_specific_to_the_model(self, tmp_path):
        backend = MagicMock(return_value="text")
        video = self._video(tmp_path)

        with patch.object(
            video_rename.Transcriber, "_extract_audio", return_value=True
        ):
            video_rename.Transcriber("base", backend=backend).transcript(video)
            video_rename.Transcriber("small", backend=backend).transcript(video)

        assert backend.call_count == 2

    def test_cache_is_specific_to_the_word_list(self, tmp_path):
        backend = MagicMock(return_value="text")
        video = self._video(tmp_path)

        with patch.object(
            video_rename.Transcriber, "_extract_audio", return_value=True
        ):
            video_rename.Transcriber("base", backend=backend).transcript(video)
            video_rename.Transcriber(
                "base", backend=backend, prompt="Glossary: Mycena."
            ).transcript(video)
            video_rename.Transcriber(
                "base", backend=backend, prompt="Glossary: Mycena."
            ).transcript(video)
            video_rename.Transcriber(
                "base", backend=backend, prompt="Glossary: Russula."
            ).transcript(video)

        assert backend.call_count == 3

    def test_word_list_is_passed_to_the_speech_model(self):
        with patch("video_rename._load_speech_backend") as load:
            video_rename.Transcriber(
                "base", prompt="Glossary: Cordyceps."
            )._ensure_backend()  # pylint: disable=protected-access

        load.assert_called_once_with("base", "Glossary: Cordyceps.")

    def test_video_without_audio_has_empty_transcript(self, tmp_path):
        backend = MagicMock()
        transcriber = video_rename.Transcriber("base", backend=backend)

        with patch.object(
            video_rename.Transcriber, "_extract_audio", return_value=False
        ):
            assert transcriber.transcript(self._video(tmp_path)) == ""

        backend.assert_not_called()

    def test_failed_transcription_is_not_cached(self, tmp_path, capsys):
        backend = MagicMock(side_effect=[ValueError("decoder error"), "second try"])
        transcriber = video_rename.Transcriber("base", backend=backend)
        video = self._video(tmp_path)

        with patch.object(
            video_rename.Transcriber, "_extract_audio", return_value=True
        ):
            assert transcriber.transcript(video) is None
            assert transcriber.transcript(video) == "second try"

        assert "Could not transcribe" in capsys.readouterr().out

    @patch("video_rename._load_speech_backend", return_value=None)
    def test_missing_speech_recognizer_is_reported(self, _load, tmp_path):
        transcriber = video_rename.Transcriber("base")

        with pytest.raises(video_rename.TranscriberUnavailable, match="faster-whisper"):
            transcriber.transcript(self._video(tmp_path))

    @patch("video_rename._load_speech_backend", side_effect=OSError("offline"))
    def test_model_that_cannot_load_is_reported_clearly(self, _load, tmp_path):
        transcriber = video_rename.Transcriber("small")

        with pytest.raises(
            video_rename.TranscriberUnavailable, match="'small' speech model"
        ):
            transcriber.transcript(self._video(tmp_path))

    @pytest.mark.skipif(not video_rename.FFMPEG_PATH, reason="FFmpeg not installed")
    def test_extracts_audio_and_detects_silent_videos(self, tmp_path):
        with_audio = tmp_path / "with_audio.mp4"
        without_audio = tmp_path / "without_audio.mp4"
        base = [video_rename.FFMPEG_PATH, "-v", "error", "-y", "-f", "lavfi"]
        subprocess.run(
            base
            + ["-i", "color=c=black:s=64x64:d=1", "-f", "lavfi"]
            + ["-i", "sine=frequency=440:duration=1", "-shortest", str(with_audio)],
            check=True,
        )
        subprocess.run(
            base + ["-i", "color=c=black:s=64x64:d=1", str(without_audio)],
            check=True,
        )

        audio = tmp_path / "audio.wav"
        assert video_rename.Transcriber._extract_audio(with_audio, audio) is True
        assert audio.stat().st_size > 44

        silent = tmp_path / "silent.wav"
        assert video_rename.Transcriber._extract_audio(without_audio, silent) is False


# --- Clip catalog ---


class TestClipCatalog:
    @staticmethod
    def _exif():
        return {
            "ImageWidth": 1080,
            "ImageHeight": 1920,
            "Duration": 125.4,
            "CreateDate": "2026:10:24 14:30:00",
            "GPSLatitude": -0.2,
            "GPSLongitude": -78.5,
        }

    @patch("video_rename.get_location_info", return_value="Ecuador")
    @patch("video_rename.get_exif_data")
    def test_row_describes_the_video(self, exif, _location, tmp_path):
        exif.return_value = self._exif()
        video = tmp_path / "trip" / "IMG_1234_cordyceps_on_ant_horizontal.mp4"
        video.parent.mkdir()
        video.write_bytes(b"x" * 2048)

        row = video_rename.build_catalog_row(video, base_dir=tmp_path)

        assert row["path"] == str(Path("trip") / video.name)
        assert row["description"] == "cordyceps on ant horizontal"
        assert row["date"] == "2026-10-24"
        assert row["location"] == "Ecuador"
        assert row["orientation"] == "vertical"
        assert row["duration"] == "2:05"
        assert row["duration_seconds"] == 125.4
        assert row["width"] == 1080 and row["height"] == 1920
        assert "transcript" not in row

    @patch("video_rename.get_location_info", return_value=None)
    @patch("video_rename.get_exif_data", return_value={})
    def test_missing_metadata_leaves_cells_blank(self, _exif, _location, tmp_path):
        video = tmp_path / "IMG_0002.mov"
        video.write_bytes(b"")

        row = video_rename.build_catalog_row(video)

        assert row["description"] == ""
        assert row["date"] == row["location"] == row["duration"] == ""
        assert row["orientation"] == "horizontal"

    def test_long_durations_include_hours(self):
        assert video_rename._format_duration(3725) == "1:02:05"
        assert video_rename._format_duration(59.6) == "1:00"

    @patch("video_rename.get_location_info", return_value=None)
    @patch("video_rename.get_exif_data")
    def test_writes_csv_and_continues_past_bad_files(
        self, exif, _location, tmp_path, capsys
    ):
        good = tmp_path / "IMG_0001_puffballs.mp4"
        bad = tmp_path / "IMG_0002.mp4"
        good.write_bytes(b"a")
        bad.write_bytes(b"b")
        exif.side_effect = [self._exif(), ValueError("unreadable")]
        output = tmp_path / "clips.csv"

        count = video_rename.write_catalog([good, bad], output, base_dir=tmp_path)

        assert count == 1
        raw = output.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")  # Excel-friendly UTF-8
        rows = list(video_rename.csv.DictReader(raw.decode("utf-8-sig").splitlines()))
        assert [row["filename"] for row in rows] == [good.name]
        assert rows[0]["description"] == "puffballs"
        assert "Could not catalog IMG_0002.mp4" in capsys.readouterr().out
        assert not list(tmp_path.glob(".clips.csv.*.tmp"))

    @patch("video_rename.get_location_info", return_value=None)
    @patch("video_rename.get_exif_data", return_value={})
    def test_transcript_columns_are_added_when_transcribing(
        self, _exif, _location, tmp_path
    ):
        video = tmp_path / "IMG_0003.mp4"
        video.write_bytes(b"a")
        transcriber = MagicMock()
        transcriber.transcript.return_value = "Look at this Amanita muscaria"
        output = tmp_path / "clips.csv"

        video_rename.write_catalog([video], output, transcriber=transcriber)

        rows = list(video_rename.csv.DictReader(output.open(encoding="utf-8-sig")))
        assert rows[0]["transcript"] == "Look at this Amanita muscaria"
        assert rows[0]["suggested_description"] == "Amanita muscaria"

    def test_refuses_to_overwrite_a_video(self, tmp_path):
        with pytest.raises(ValueError, match="over a video"):
            video_rename.write_catalog([], tmp_path / "clips.mp4")


# --- Interactive transcripts ---


class TestInteractiveTranscripts:
    @staticmethod
    def _server(transcriber=None, items=2, scan_complete=True):
        return SimpleNamespace(
            stop_event=Event(),
            review_lock=Lock(),
            review_items=[
                {"id": index, "path": Path(f"IMG_{index}.mp4")}
                for index in range(items)
            ],
            scan_complete=scan_complete,
            transcriber=transcriber,
            transcripts={},
            transcript_priority=None,
            transcription_failed=False,
        )

    def test_disabled_without_a_transcriber(self):
        server = self._server()

        response = video_rename._transcript_response(server, server.review_items[0])

        assert response == {"status": "disabled"}

    def test_pending_request_prioritizes_the_video_on_screen(self):
        server = self._server(transcriber=MagicMock(), items=3)

        response = video_rename._transcript_response(server, server.review_items[2])

        assert response == {"status": "pending"}
        item, _path = video_rename._next_transcript_item(server)
        assert item["id"] == 2

    def test_works_ahead_of_the_reviewer(self):
        server = self._server(transcriber=MagicMock(), items=4)
        server.transcript_priority = 1
        server.transcripts = {1: {"status": "ready"}}

        item, _path = video_rename._next_transcript_item(server)

        assert item["id"] == 2

    def test_background_worker_transcribes_and_suggests(self):
        transcriber = MagicMock()
        transcriber.transcript.side_effect = [
            "Ophiocordyceps australis on an ant",
            None,
        ]
        server = self._server(transcriber=transcriber)

        video_rename._transcribe_review_items(server)

        assert server.transcripts[0]["status"] == "ready"
        assert server.transcripts[0]["suggestion"].startswith(
            "Ophiocordyceps australis"
        )
        assert server.transcripts[1] == {"status": "unavailable"}
        response = video_rename._transcript_response(server, server.review_items[0])
        assert response["transcript"] == "Ophiocordyceps australis on an ant"

    def test_unavailable_recognizer_stops_waiting_in_the_browser(self, capsys):
        transcriber = MagicMock()
        transcriber.transcript.side_effect = video_rename.TranscriberUnavailable(
            "No speech recognizer is installed."
        )
        server = self._server(transcriber=transcriber)

        video_rename._transcribe_review_items(server)

        response = video_rename._transcript_response(server, server.review_items[1])
        assert response == {"status": "unavailable"}
        assert "Transcription stopped" in capsys.readouterr().out

    def test_items_response_reports_whether_transcripts_are_on(self):
        server = self._server(transcriber=MagicMock())
        server.scan_progress = server.scan_total = 2
        server.dry_run = False

        # Asking only for items past the end keeps this about the flag itself.
        assert _review_items_response(server, 2)["transcripts"] is True

    def test_suggestion_is_only_used_when_asked(self):
        # The description stays empty until the reviewer presses Tab or the
        # suggestion button, so a suggestion is never saved by accident.
        assert "input.value = info.suggestion" in _INTERACTIVE_HTML
        assert "event.key === 'Tab'" in _INTERACTIVE_HTML
        assert "$('description').value = item.description || '';" in (_INTERACTIVE_HTML)


class TestCatalogArguments:
    @pytest.mark.parametrize(
        "extra, message",
        [
            (["--catalog", "c.csv", "--interactive"], "cannot be combined"),
            (["--transcribe"], "--transcribe can only be used"),
        ],
    )
    @patch("video_rename.get_video_files")
    def test_invalid_combinations_are_rejected_before_scanning(
        self, get_files, extra, message, capsys
    ):
        argv = ["video_rename.py", "/videos"] + extra
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exit_info:
            video_rename.main()

        assert exit_info.value.code == 2
        get_files.assert_not_called()
        assert message in capsys.readouterr().err

    @patch("video_rename.write_catalog", return_value=2)
    @patch("video_rename.get_video_files")
    def test_catalog_mode_does_not_rename(self, get_files, write, tmp_path, capsys):
        get_files.return_value = [tmp_path / "b.mp4", tmp_path / "A.mp4"]
        argv = ["video_rename.py", str(tmp_path), "--catalog", "clips.csv"]

        with (
            patch.object(sys, "argv", argv),
            patch("video_rename.EXIFTOOL_PATH", "/usr/bin/exiftool"),
            patch("video_rename.process_file") as process,
        ):
            video_rename.main()

        process.assert_not_called()
        files, output, base_dir, transcriber, _debug = write.call_args.args
        assert [path.name for path in files] == ["A.mp4", "b.mp4"]
        assert output == "clips.csv"
        assert base_dir == tmp_path.resolve()
        assert transcriber is None
        assert "Wrote 2 video(s) to clips.csv" in capsys.readouterr().out


# --- Transcript files ---


class TestTranscriptFiles:
    def test_saves_a_marked_text_file_beside_the_video(self, tmp_path):
        video = tmp_path / "IMG_0001.mov"
        video.write_bytes(b"v")

        path = video_rename.save_transcript_file(
            video, "Look at this Amanita muscaria", "/models/small.en"
        )

        assert path == tmp_path / "IMG_0001.txt"
        text = path.read_text(encoding="utf-8")
        assert text.startswith(video_rename.TRANSCRIPT_FILE_MARKER + "\n")
        assert "Speech model: small.en." in text
        assert "/models" not in text
        assert text.endswith("\n\nLook at this Amanita muscaria\n")
        assert not list(tmp_path.glob(".*.tmp"))

    def test_silent_videos_get_no_file(self, tmp_path):
        video = tmp_path / "IMG_0002.mov"

        assert video_rename.save_transcript_file(video, "") is None
        assert not (tmp_path / "IMG_0002.txt").exists()

    def test_never_overwrites_someone_elses_text_file(self, tmp_path, capsys):
        notes = tmp_path / "IMG_0003.txt"
        notes.write_text("my field notes", encoding="utf-8")

        result = video_rename.save_transcript_file(tmp_path / "IMG_0003.mov", "hi")

        assert result is None
        assert notes.read_text(encoding="utf-8") == "my field notes"
        assert "already exists" in capsys.readouterr().out

    def test_updates_its_own_file(self, tmp_path):
        video = tmp_path / "IMG_0004.mov"
        video_rename.save_transcript_file(video, "first")

        video_rename.save_transcript_file(video, "second")

        assert (
            (tmp_path / "IMG_0004.txt")
            .read_text(encoding="utf-8")
            .endswith("\nsecond\n")
        )

    def test_rename_moves_only_its_own_transcript(self, tmp_path):
        old = tmp_path / "IMG_0005.mov"
        new = tmp_path / "IMG_0005_puffballs.mov"
        video_rename.save_transcript_file(old, "puffballs everywhere")

        video_rename._move_transcript_file(old, new)

        assert not (tmp_path / "IMG_0005.txt").exists()
        assert (tmp_path / "IMG_0005_puffballs.txt").exists()

        other_old = tmp_path / "IMG_0006.mov"
        (tmp_path / "IMG_0006.txt").write_text("not ours", encoding="utf-8")
        video_rename._move_transcript_file(other_old, tmp_path / "IMG_0006_x.mov")
        assert (tmp_path / "IMG_0006.txt").exists()
        assert not (tmp_path / "IMG_0006_x.txt").exists()

    def test_interactive_rename_carries_the_transcript(self, tmp_path):
        old = tmp_path / "IMG_1234_horizontal.mp4"
        old.write_bytes(b"a")
        video_rename.save_transcript_file(old, "a lovely beach")
        handler = TestInteractiveRename._handler()
        item = TestInteractiveRename._item(old)

        handler._rename(item, "Beach")

        assert transcript_text(item["path"]).endswith("\na lovely beach\n")
        assert not (tmp_path / "IMG_1234_horizontal.txt").exists()

    def test_deleting_a_video_removes_its_transcript(self, tmp_path, fake_trash):
        video = tmp_path / "delete-me.mp4"
        video.write_bytes(b"v")
        video_rename.save_transcript_file(video, "blurry")

        _delete_review_item(
            TestInteractiveDelete._server(False), {"id": 0, "path": video}
        )

        assert not (tmp_path / "delete-me.txt").exists()
        assert (fake_trash / "delete-me.txt").exists()

    def test_review_saves_transcripts_under_the_current_name(self, tmp_path):
        old = tmp_path / "IMG_7.mp4"
        renamed = tmp_path / "IMG_7_moths.mp4"
        server = TestInteractiveTranscripts._server(items=1)
        server.review_items[0]["path"] = old
        server.dry_run = False
        server.save_transcripts = True

        def transcribe(_path):
            # The reviewer renames the video while it is being transcribed.
            server.review_items[0]["path"] = renamed
            return "so many moths"

        server.transcriber = MagicMock(model_name="small.en")
        server.transcriber.transcript.side_effect = transcribe

        video_rename._transcribe_review_items(server)

        assert transcript_text(renamed).endswith("\nso many moths\n")
        assert not (tmp_path / "IMG_7.txt").exists()

    def test_review_dry_run_writes_nothing(self, tmp_path):
        server = TestInteractiveTranscripts._server(items=1)
        server.review_items[0]["path"] = tmp_path / "IMG_8.mp4"
        server.dry_run = True
        server.save_transcripts = True
        server.transcriber = MagicMock(model_name="base")
        server.transcriber.transcript.return_value = "hello"

        video_rename._transcribe_review_items(server)

        assert not list(tmp_path.iterdir())

    @patch("video_rename.get_location_info", return_value=None)
    @patch("video_rename.get_exif_data", return_value={})
    def test_catalog_can_save_transcripts(self, _exif, _location, tmp_path):
        video = tmp_path / "IMG_0009.mp4"
        video.write_bytes(b"a")
        transcriber = MagicMock(model_name="base")
        transcriber.transcript.return_value = "Russula emetica"

        video_rename.write_catalog(
            [video],
            tmp_path / "clips.csv",
            transcriber=transcriber,
            save_transcripts=True,
        )

        assert transcript_text(video).endswith("\nRussula emetica\n")

    @patch("video_rename.get_video_files")
    def test_save_transcripts_requires_transcribe(self, get_files, capsys):
        argv = ["video_rename.py", "/videos", "--interactive", "--save-transcripts"]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit):
            video_rename.main()

        get_files.assert_not_called()
        assert "--save-transcripts can only be used" in capsys.readouterr().err


def transcript_text(video):
    return video_rename.transcript_file_path(video).read_text(encoding="utf-8")


@pytest.fixture
def fake_trash(tmp_path, monkeypatch):
    """Replace the system Trash with a folder so tests never touch it."""
    trash = tmp_path / "Trash"
    trash.mkdir()

    def fake_move_to_trash(path):
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(str(path))
        path.rename(trash / path.name)

    monkeypatch.setattr(video_rename, "move_to_trash", fake_move_to_trash)
    return trash


class TestMoveToTrash:
    def test_uses_send2trash_when_installed(self, tmp_path, monkeypatch):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"v")
        calls = []
        module = SimpleNamespace(send2trash=calls.append)
        monkeypatch.setitem(sys.modules, "send2trash", module)

        video_rename.move_to_trash(video)

        assert calls == [str(video)]

    def test_uses_finder_on_macos(self, tmp_path, monkeypatch):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"v")
        monkeypatch.setitem(sys.modules, "send2trash", None)
        monkeypatch.setattr(video_rename.sys, "platform", "darwin")
        monkeypatch.setattr(
            video_rename.shutil, "which", lambda name: f"/usr/bin/{name}"
        )
        commands = []

        def fake_run(command, **_kwargs):
            commands.append(command)
            return SimpleNamespace(returncode=0, stderr="")

        monkeypatch.setattr(video_rename.subprocess, "run", fake_run)

        video_rename.move_to_trash(video)

        assert commands[0][0] == "osascript"
        assert 'tell application "Finder" to delete' in commands[0][2]
        assert commands[0][-1] == str(video.resolve())

    def test_finder_failure_raises_and_keeps_file(self, tmp_path, monkeypatch):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"v")
        monkeypatch.setitem(sys.modules, "send2trash", None)
        monkeypatch.setattr(video_rename.sys, "platform", "darwin")
        monkeypatch.setattr(
            video_rename.shutil, "which", lambda name: f"/usr/bin/{name}"
        )
        monkeypatch.setattr(
            video_rename.subprocess,
            "run",
            lambda *_a, **_k: SimpleNamespace(returncode=1, stderr="Not allowed"),
        )

        with pytest.raises(video_rename.TrashUnavailableError, match="Not allowed"):
            video_rename.move_to_trash(video)
        assert video.exists()

    def test_never_deletes_when_no_trash_exists(self, tmp_path, monkeypatch):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"v")
        monkeypatch.setitem(sys.modules, "send2trash", None)
        monkeypatch.setattr(video_rename.sys, "platform", "linux")
        monkeypatch.setattr(video_rename.shutil, "which", lambda _name: None)

        with pytest.raises(video_rename.TrashUnavailableError, match="send2trash"):
            video_rename.move_to_trash(video)
        assert video.exists()

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            video_rename.move_to_trash(tmp_path / "gone.mp4")


class TestVocabulary:
    def test_reads_terms_skipping_comments_blanks_and_repeats(self, tmp_path):
        word_list = tmp_path / "words.txt"
        word_list.write_text(
            "# Genera\nMycena\n\n  Cordyceps  \nmycena\n# People\nAlan Rockefeller\n",
            encoding="utf-8",
        )

        assert video_rename.load_vocabulary(word_list) == [
            "Mycena",
            "Cordyceps",
            "Alan Rockefeller",
        ]

    def test_prompt_lists_the_terms(self):
        assert (
            video_rename.vocabulary_prompt(["Mycena", "Lepiota luteophylla"])
            == "Glossary: Mycena, Lepiota luteophylla."
        )

    def test_empty_list_gives_no_prompt(self):
        assert video_rename.vocabulary_prompt([]) is None

    def test_faster_whisper_receives_the_prompt(self, monkeypatch):
        model = MagicMock()
        model.transcribe.return_value = ([SimpleNamespace(text=" Mycena ")], None)
        module = SimpleNamespace(WhisperModel=MagicMock(return_value=model))
        monkeypatch.setitem(sys.modules, "faster_whisper", module)

        backend = video_rename._load_speech_backend("base", "Glossary: Mycena.")

        assert backend("clip.wav") == "Mycena"
        assert model.transcribe.call_args.kwargs["initial_prompt"] == (
            "Glossary: Mycena."
        )
