# Changelog

Notable changes to Video Renamer are documented here. Because the project has
not used Git tags, entries are grouped by commit date rather than release tag.

## 2026-11-08

### Changed

- Look up a video's location only after it has stayed on the review screen
  briefly or a description is being typed, so skipping quickly through videos
  no longer queues a serialized Nominatim request for each one. The scanner
  still checks an ambiguous single-word suffix after a camera-style name
  before the video is shown, as described in the README.
- Retry a location lookup that the service could not complete when the video
  is revisited or renamed, instead of treating the first failure as final.
- Pause online geocoding for a minute after two consecutive network or service
  failures instead of waiting out the full request timeout for every file.
- Stop FFmpeg preview conversions after five minutes and terminate any still
  running when the review ends, so a stalled conversion cannot block deleting
  the same video or leave the temporary preview directory behind.
- Documented the actual minimum Python version (3.7) and the three-decimal
  coordinate rounding used by the geocoding cache.

### Fixed

- Refresh the description field after a location lookup removes a recognized
  location token, so `--include-described` no longer proposes names such as
  `..._Mexico_Mexico_vertical.mp4`.
- Treat a single word after any camera-style name (Pixel timestamps,
  `video_001`, date-time names) as a possible batch-mode location, not only
  after `IMG`/`DSC`-style identifiers, so those files are offered for review.
- Keep the longest camera-style prefix when splitting a name, so `video_001`
  is no longer split into `video` plus a description starting with `001`.
- Use the trailing orientation token when a filename contains both
  `vertical` and `horizontal`.
- Fall back to a bare `USA` token when a US geocoding result has no state,
  instead of producing `USA_`.
- Reject `--include-described` without `--interactive` before scanning for
  files, including when no videos are found.
- Answer with 404 when a video disappears before it is streamed, and send a
  zero content length for an empty file.
- Ignore duplicate paths, such as a file given together with its directory.

## 2026-10-24

### Added

- Added a pinned `geopy` dependency range in `requirements.txt`.
- Added test coverage for command-line interruption handling.
- Added `--interactive` browser-based video review with native playback,
  seeking controls, live filename previews, skip/previous navigation, and
  keyboard shortcuts.
- Added confirmed deletion from interactive review, with non-destructive
  session-only behavior under `--dry-run`.
- Added filename heuristics that distinguish descriptive names from camera
  identifiers, UUIDs, timestamps, and metadata-only names.
- Added recording dates to interactive filenames when they are not already
  present.
- Added optional FFmpeg-powered browser previews that copy compatible video
  streams and convert unsupported audio such as PCM to AAC.
- Added persistent reverse-geocoding results under the user's cache directory.
- Added comprehensive tests for interactive naming, incremental scanning,
  geocoding courtesy, filename detection, and browser audio previews.

### Changed

- Handle Ctrl-C cleanly, print a concise cancellation message, and exit with
  status code 130.
- Open interactive review immediately while local metadata scanning continues
  in the background.
- Skip ExifTool and network lookup entirely for filenames that already contain
  a clear description.
- Defer reverse geocoding until a video is actually displayed (except for an
  ambiguous single-word suffix after a camera name, which is checked while
  scanning), coalesce nearby coordinates, serialize requests at one every 1.1
  seconds, honor `Retry-After`, and use bounded backoff with a temporary
  cooldown for repeated rate limits.
- Poll large interactive scans incrementally instead of retransmitting the
  complete growing item list.
- Allow the Nominatim domain to be changed with
  `VIDEO_RENAME_NOMINATIM_DOMAIN` and identify the application with a specific
  User-Agent.
- Updated the script and documentation to version 1.2.

### Fixed

- Avoid adding the same recording date twice when the original filename uses a
  compact date such as `20130721` and metadata supplies `2013-07-21`.
- Restore sound in browser playback for videos whose audio codec is unsupported
  by converting only the temporary preview's audio stream.
- Stop repeated 429 responses from producing request storms.
- Reject invalid placeholder dates such as `0000-00-00` and continue searching
  later metadata fields for a valid recording date.
- Preserve international location suffixes produced by batch mode when deciding
  whether a camera filename still needs a description.
- Regenerate browser-compatible audio previews after their temporary files are
  evicted.
- Harden the local review server against DNS rebinding, cross-origin mutation
  requests, and invalid negative request lengths.

## 2026-03-31

### Added

- Added a pytest suite covering orientation detection, rotation parsing,
  filename normalization, location and orientation matching, path generation,
  dry runs, and collision handling.

### Changed

- Updated the script version to 1.1.
- Clarified that existing filename components keep their order while missing
  location and orientation components are appended in canonical order.
- Made dry runs report destination collisions explicitly instead of presenting
  them as successful proposed renames.
- Added clearer warnings for directories that cannot be read during recursive
  scans.

## 2026-03-13

### Changed

- Refactored filename construction, metadata parsing, path display, and video
  detection into focused helper functions.
- Simplified batch processing while preserving per-file error isolation so one
  bad video does not stop the rest of a run.
- Removed a redundant absolute-path check.

### Fixed

- Validate ExifTool JSON output before reading its first result.
- Cache failed reverse-geocoding lookups as well as successful ones.

## 2026-03-12

### Changed

- Reformatted the code with Black and resolved pylint findings.
- Improved country-name checking in existing filenames.

### Fixed

- Corrected two edge cases in metadata and filename processing.

## 2025-12-02

### Added

- Initial command-line video renamer with GPS-based reverse geocoding and
  metadata-based horizontal or vertical orientation detection.
- Support for individual files, directories, recursive scans, dry runs, and
  debug output.
- Support for MP4, MOV, M4V, AVI, MKV, HEVC, MPG, and MPEG files.
- Collision protection and idempotent handling of filenames that already
  contain location or orientation information.
- MIT license and project documentation.

### Changed

- Continue adding orientation information when a filename already contains a
  recognized location.
- Improve compatibility with Python versions that do not provide
  `Path.is_relative_to`.
- Recognize multi-word and separator-free location names in existing
  filenames.

### Fixed

- Corrected filename location detection and several initial rename-path edge
  cases.
