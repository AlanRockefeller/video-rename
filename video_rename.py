#!/usr/bin/env python3

# video_rename.py version 1.0 by Alan Rockefeller
# November 29, 2025

import argparse
import os
import subprocess
import json
import shutil
import sys
from pathlib import Path

try:
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderUnavailable, GeocoderServiceError
except ImportError:
    print("Error: 'geopy' library not found. Please install it with 'pip install geopy'")
    sys.exit(1)

# --- Constants ---

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.avi', '.mkv', '.hevc', '.mpg', '.mpeg'}

# A mapping from full state names to two-letter abbreviations.
# geopy returns full state names, but we need abbreviations for the filename.
US_STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    "District of Columbia": "DC", "American Samoa": "AS", "Guam": "GU",
    "Northern Mariana Islands": "MP", "Puerto Rico": "PR", "United States Virgin Islands": "VI",
}

# --- Location Constants for Filename Checking ---
# All names are stored in lowercase for case-insensitive matching.
COUNTRY_NAMES = {
    "afghanistan", "albania", "algeria", "andorra", "angola", "antigua and barbuda",
    "argentina", "armenia", "australia", "austria", "azerbaijan", "bahamas", "bahrain",
    "bangladesh", "barbados", "belarus", "belgium", "belize", "benin", "bhutan", "bolivia",
    "bosnia and herzegovina", "botswana", "brazil", "brunei", "bulgaria", "burkina faso",
    "burundi", "cabo verde", "cambodia", "cameroon", "canada", "central african republic",
    "chad", "chile", "china", "colombia", "comoros", "congo", "costa rica", "côte d'ivoire",
    "croatia", "cuba", "cyprus", "czechia", "denmark", "djibouti", "dominica", "dominican republic",
    "ecuador", "egypt", "el salvador", "equatorial guinea", "eritrea", "estonia", "eswatini",
    "ethiopia", "fiji", "finland", "france", "gabon", "gambia", "georgia", "germany", "ghana",
    "greece", "grenada", "guatemala", "guinea", "guinea-bissau", "guyana", "haiti", "holy see",
    "honduras", "hungary", "iceland", "india", "indonesia", "iran", "iraq", "ireland", "israel",
    "italy", "jamaica", "japan", "jordan", "kazakhstan", "kenya", "kiribati", "kuwait",
    "kyrgyzstan", "laos", "latvia", "lebanon", "lesotho", "liberia", "libya", "liechtenstein",
    "lithuania", "luxembourg", "madagascar", "malawi", "malaysia", "maldives", "mali", "malta",
    "marshall islands", "mauritania", "mauritius", "mexico", "micronesia", "moldova", "monaco",
    "mongolia", "montenegro", "morocco", "mozambique", "myanmar", "namibia", "nauru", "nepal",
    "netherlands", "new zealand", "nicaragua", "niger", "nigeria", "north korea", "north macedonia",
    "norway", "oman", "pakistan", "palau", "palestine", "panama", "papua new guinea", "paraguay",
    "peru", "philippines", "poland", "portugal", "qatar", "romania", "russia", "rwanda",
    "saint kitts and nevis", "saint lucia", "saint vincent and the grenadines", "samoa",
    "san marino", "sao tome and principe", "saudi arabia", "senegal", "serbia", "seychelles",
    "sierra leone", "singapore", "slovakia", "slovenia", "solomon islands", "somalia",
    "south africa", "south korea", "south sudan", "spain", "sri lanka", "sudan", "suriname",
    "sweden", "switzerland", "syria", "tajikistan", "tanzania", "thailand", "timor-leste",
    "togo", "tonga", "trinidad and tobago", "tunisia", "turkey", "turkmenistan", "tuvalu",
    "uganda", "ukraine", "united arab emirates", "united kingdom", "united states", "usa",
    "uruguay", "uzbekistan", "vanuatu", "venezuela", "vietnam", "yemen", "zambia", "zimbabwe"
}
# Only check for full state names (e.g., "California"), not abbreviations ("CA").
STATE_NAMES = {name.lower() for name in US_STATES.keys()}
ALL_LOCATIONS = COUNTRY_NAMES | STATE_NAMES



# --- Geocoding ---

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
        location = GEOCODER.reverse(coords, language='en', timeout=10)
        if location and 'address' in location.raw:
            address = location.raw['address']
            country = address.get('country', '')
            country_code = address.get('country_code', '').upper()

            if country_code == 'US':
                state = address.get('state', '')
                state_abbr = US_STATES.get(state, state) # Fallback to full name if not in dict
                result = f"USA_{state_abbr}"
            else:
                # Replace spaces for filename-friendliness
                result = country.replace(' ', '')
            
            GEOCODE_CACHE[coords] = result
            return result
    except (GeocoderTimedOut, GeocoderUnavailable, GeocoderServiceError) as e:
        print(f"Warning: Geocoding service error for {coords}: {e}")
        return None

    GEOCODE_CACHE[coords] = None
    return None


# --- EXIF and File Operations ---

def get_exif_data(file_path):
    """Extracts EXIF data from a file using exiftool."""
    try:
        result = subprocess.run(
            ['exiftool', '-json', '-n', str(file_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=True,
        )
        # exiftool returns a list with one JSON object
        return json.loads(result.stdout)[0]
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
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

def get_video_files(paths, recursive):
    """Yields all video files from the given paths."""
    for path_str in paths:
        path = Path(path_str)
        if path.is_file():
            if path.suffix.lower() in VIDEO_EXTENSIONS:
                yield path
        elif path.is_dir():
            if recursive:
                for dirpath, _, filenames in os.walk(path):
                    for filename in filenames:
                        file_path = Path(dirpath) / filename
                        if file_path.suffix.lower() in VIDEO_EXTENSIONS:
                            yield file_path
            else: # Not recursive, so only top-level
                for item in path.iterdir():
                    if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                        yield item

# --- Main Logic ---

def process_file(file_path, dry_run, debug, is_recursive, base_dir):
    """
    Processes a single video file: extracts metadata, determines the new name,
    and performs the rename.
    """
    stem = file_path.stem
    
    
    # Check if filename already contains a location (case-insensitive).
    # Normalize by treating '-' and '_' as spaces and also checking a compact
    # form with spaces removed so that both "Costa Rica" and "CostaRica" match.
    normalized_stem = stem.replace('-', ' ').replace('_', ' ').lower()
    normalized_compact = normalized_stem.replace(' ', '')
    found_loc = None
    for loc in ALL_LOCATIONS:
        if loc in normalized_stem or loc.replace(' ', '') in normalized_compact:
            found_loc = loc
            break

    if found_loc:
        print(f"[NOTICE] Skipping {file_path.name}: Already contains location '{found_loc}'.")
        return

    exif_data = get_exif_data(file_path)

    # 1. Determine orientation
    width = exif_data.get('ImageWidth')
    height = exif_data.get('ImageHeight')
    
    rotation_val = exif_data.get('Rotation')
    rotation = None
    if rotation_val is not None:
        try:
            rotation = int(rotation_val)
        except (ValueError, TypeError):
            rotation = None

    orientation = get_orientation(width, height, rotation)

    if debug:
        print(f"[DEBUG] file: {file_path.name}, width: {width}, height: {height}, rotation: {rotation}, orientation: {orientation}")

    # 2. Determine location
    latitude = exif_data.get('GPSLatitude')
    longitude = exif_data.get('GPSLongitude')
    location_str = get_location_info(latitude, longitude)
    
    # 3. Construct new name
    ext = file_path.suffix
    
    components = [stem]
    if location_str:
        components.append(location_str)
    
    # Check if orientation already exists in the stem (case-insensitive)
    stem_lower = stem.lower()
    if "_horizontal" not in stem_lower and "_vertical" not in stem_lower:
        components.append(orientation)
    
    new_stem = "_".join(components)

    new_path = file_path.with_name(new_stem + ext)

    if new_path == file_path:
        return # No change needed

    # Determine display name for original file
    original_display_name = str(file_path.name)
    if is_recursive and base_dir:
        try:
            original_display_name = str(file_path.relative_to(base_dir))
        except ValueError:
            # Fallback if file_path is not truly relative to base_dir
            pass

    # 4. Perform rename
    if dry_run:
        print(f"[DRY] {original_display_name} → {new_path.name}")
    else:
        if new_path.exists():
            print(f"Warning: Destination file {new_path} already exists. Skipping.")
            return
        try:
            shutil.move(file_path, new_path)
            print(f"[RENAME] {original_display_name} → {new_path.name}")
        except OSError as e:
            print(f"Error: Failed to rename {file_path.name}. Reason: {e}")

def main():
    """Main function to parse arguments and orchestrate the renaming process."""
    
    # Custom help message for no-argument case
    if len(sys.argv) == 1:
        print("Usage: video_rename.py [PATH ...] [--recursive] [--dry-run] [--debug]")
        print("\nRenames video files based on GPS location and video orientation from EXIF data.")
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
"""
    )
    parser.add_argument(
        'paths',
        nargs='+',
        help='One or more paths to video files or directories.'
    )
    parser.add_argument(
        '-r', '--recursive',
        action='store_true',
        help='Recursively scan for videos in any specified directories.'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print proposed renames but do not modify any files.'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug printing for orientation detection.'
    )

    args = parser.parse_args()

    if not shutil.which("exiftool"):
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
            processed_file_path = file_path.resolve() if not file_path.is_absolute() else file_path
            process_file(processed_file_path, args.dry_run, args.debug, args.recursive, base_dir)
        except Exception as e:
            print(f"An unexpected error occurred while processing {file_path.name}: {e}")

if __name__ == '__main__':
    main()
