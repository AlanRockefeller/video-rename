# Video Renamer

# By Alan Rockefeller
# Version 1.0
# November 29, 2025


A Python command-line tool to intelligently rename video files based on their metadata. This script extracts GPS and resolution data from a video's EXIF information to automatically add location and orientation information to the filename.

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

## Requirements

- Python 3.6+
- `exiftool`: This must be installed and accessible in your system's PATH. You can find installation instructions at [exiftool.org](https://exiftool.org/install.html).
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
