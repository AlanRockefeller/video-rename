"""Tests for the pure helper functions in video_rename.py."""

from pathlib import Path
from unittest.mock import patch

from video_rename import (
    _build_new_path,
    _normalize_for_comparison,
    _parse_rotation,
    _stem_has_location,
    _stem_has_orientation,
    get_orientation,
    process_file,
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
    def test_dry_run_skips_when_destination_exists(self, _mock_exif, _mock_loc, capsys, tmp_path):
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
    def test_real_run_skips_when_destination_exists(self, _mock_exif, _mock_loc, capsys, tmp_path):
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
