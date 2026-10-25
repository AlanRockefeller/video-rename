# Video Renamer

# By Alan Rockefeller
# Version 1.2
# October 24, 2026


A Python command-line tool to give videos useful, searchable filenames. It can
automatically add metadata, or open an interactive review screen where you watch
each undescribed video and type a description while previewing the new name.

## Description

This tool processes video files and renames them according to the following pattern:

`<original-name>_<location>_<orientation>.<ext>`

-   **Location**: Determined by reverse geocoding the GPS coordinates from the video's metadata.
    -   For videos taken in the USA, the format is `USA_<StateAbbr>` (e.g., `USA_CA`).
    -   For other countries, the country name is used (e.g., `Ecuador`).
    -   If no GPS data is found, the location tag is omitted.
-   **Orientation**: Determined by the video's resolution and rotation metadata.
    -   `horizontal`: If the video's width is greater than or equal to its height.
    -   `vertical`: If the video's height is greater than its width, or if a `Rotation` tag of 90 or 270 degrees is present (common in smartphone videos).

The script is designed to be safe and idempotent:
- It will not overwrite existing files.
- It will skip renaming files that already appear to contain a country or US state name.
- It will not add orientation information (`_horizontal` or `_vertical`) if one is already present.

## Interactive review

Interactive mode opens a private local page in your browser. It provides native
video playback and scrubbing, short seek buttons, and a description field. The
proposed filename changes as you type. Choose **Rename & next** to apply it or
**Skip** to move on without changing the file.

The review screen opens immediately. Metadata scanning continues without
blocking the interface, and matching videos appear as soon as they are
ready—even when the directory contains thousands of files. Files whose
names clearly contain descriptions are skipped without running ExifTool or
making any network request. Reverse geocoding is deferred until a video is
actually shown in the review screen. The only exception is an ambiguous
single-word suffix after a camera identifier, which is checked so an existing
international location such as `IMG_1234_Mexico_horizontal` is not mistaken for
a description.

```bash
python3 video_rename.py /path/to/videos --interactive
```

By default, the review only includes files that appear to lack a description.
Camera names such as `IMG_1234`, phone timestamps, and UUID filenames count as
undescribed. Names made only from dates, times, and technical markers such as
`1080p` are also undescribed; meaningful words count as a description. Add
`--include-described` to review and edit those files too.

Interactive names use this pattern, omitting unavailable metadata:

`<camera-name>_<description>_<date>_<location>_<orientation>.<ext>`

For example:

`IMG_1234_bear_fishing_2026-10-24_USA_CA_horizontal.mp4`

Useful controls:

- `Ctrl+Enter`: rename and go to the next video
- `Ctrl+Right Arrow`: skip to the next video
- `Alt+Left/Right Arrow`: seek backward or forward five seconds
- **Delete…**: permanently delete the current video after confirming its exact
  filename (`--dry-run` only removes it from the current review)
- **Open in video player**: use the system player when the browser does not
  support a video's codec

When FFmpeg is installed, interactive mode detects audio formats that browsers
usually cannot play (such as PCM audio in a MOV file). It creates a temporary
MP4 preview by copying the video stream unchanged and converting only the audio
to AAC. At most one converted preview is retained, and it is removed when the
review session ends.

The review server only listens on `127.0.0.1`, validates the local request host,
requires JSON for every modifying request, and stops when you finish. You can
combine `--interactive` with `--recursive` or `--dry-run`.

Location lookup uses OpenStreetMap's Nominatim service conservatively: requests
are serialized and limited to at most one every 1.1 seconds, nearby coordinates
share a cache entry, and successful/no-result lookups are persisted at
`$XDG_CACHE_HOME/video-rename/geocode.json` (normally
`~/.cache/video-rename/geocode.json`). A rate-limit response honors the
service's `Retry-After` value, or uses bounded exponential backoff when none is
provided. Repeated rate limits cause a temporary cooldown rather than a request
storm. Set `VIDEO_RENAME_NOMINATIM_DOMAIN` to use a different Nominatim provider
or your own instance. Location data is ©
[OpenStreetMap contributors](https://www.openstreetmap.org/copyright); see the
[public Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/).

## Requirements

- Python 3.6+
- `exiftool`: This must be installed and accessible in your system's PATH. You can find installation instructions at [exiftool.org](https://exiftool.org/install.html).
- `ffmpeg` and `ffprobe`: Optional, but recommended for browser-compatible audio previews.
- `geopy` Python library.

## Installation

1.  **Clone the repository or download the script.**

2.  **Install `exiftool` if it doesn't exist on your system yet** 

3.  **Install Python dependencies:**
    Navigate to the script's directory and run:
    ```bash
    pip install geopy
    ```

## Usage

You can run the script by passing one or more paths to video files or directories.

```bash
python3 video_rename.py [PATHS...] [OPTIONS]
```

### Arguments

-   `PATHS`: One or more paths. Can be a path to a single video file, multiple video files, a directory, or a mix.

### Options

-   `-r`, `--recursive`: Recursively scan for videos in any specified directories.
-   `--dry-run`: Print the proposed renames without actually changing any files. This is highly recommended for the first run.
-   `-i`, `--interactive`: Open the video review screen and add descriptions.
-   `--include-described`: Also show videos that already appear to have a description (interactive mode only).
-   `--debug`: Enable debug printing, which shows detailed metadata (width, height, rotation) for each file processed.

## Examples

#### Do a dry run on all videos in the current directory and all subdirectories
```bash
# Make sure to use '.' or a directory name, not a file glob
python3 video_rename.py . --recursive --dry-run
```

#### Rename a single video file
```bash
python3 video_rename.py "/path/to/my/video_001.mp4"
```

#### Interactively describe videos in a directory tree
```bash
python3 video_rename.py /path/to/videos --recursive --interactive
```

#### Rename multiple specific files
```bash
python3 video_rename.py "20250101_123000.mov" "20250102_140000.mp4"
```

#### See debug output for a specific file
```bash
python3 video_rename.py my_rotated_video.mp4 --debug
```

## Supported Video Formats

The script will process files with the following extensions (case-insensitive):
- `.mp4`
- `.mov`
- `.m4v`
- `.avi`
- `.mkv`
- `.hevc`
- `.mpg`
- `.mpeg`


## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.

## Contact

Contact me if you have any issues or suggestions for improvement - My email address is my full name at gmail, or message me on Facebook, Linkedin or Instagram

Project Link: [https://github.com/AlanRockefeller/video-rename](https://github.com/AlanRockefeller/video-rename)
