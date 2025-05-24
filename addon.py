import os
import re
import json
import asyncio
import aiohttp
import aiofiles
from multiprocessing import cpu_count
from asyncio import Semaphore
import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
from unidecode import unidecode
from requests_cache import CachedSession
from rapidfuzz import fuzz, process
import shutil
from xml.etree.ElementTree import Element, SubElement, ElementTree
from datetime import datetime # Import datetime for dateadded in NFOs
import time # Import time for runtime calculation
import sys # Import sys for atexit and sys.exit

# Kodi settings
ADDON = xbmcaddon.Addon()
SERVER_ADD = ADDON.getSetting('server_address')
USERNAME = ADDON.getSetting('username')
PASSWORD = ADDON.getSetting('password')
MOVIES_DIR = ADDON.getSetting('movies_dir')
TVSHOWS_DIR = ADDON.getSetting('tvshows_dir')
SPORT_DIR = ADDON.getSetting('sport_dir') # Added SPORT_DIR
TMDB_API_KEY = ADDON.getSetting('tmdb_api_key')

if not SERVER_ADD.startswith("http://"):
    SERVER_ADD = f"http://{SERVER_ADD}"

M3U_URL = f'{SERVER_ADD}/get.php?username={USERNAME}&password={PASSWORD}&type=m3u_plus&output=mpegts'
SERIES_API_URL = f'{SERVER_ADD}/player_api.php?username={USERNAME}&password={PASSWORD}&action=get_series'
VOD_API_URL = f'{SERVER_ADD}/player_api.php?username={USERNAME}&password={PASSWORD}&action=get_vod_streams'

# Define paths for JSON cache files
CACHE_DIR = os.path.join(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')), 'cache')
SERIES_JSON_PATH = os.path.join(CACHE_DIR, 'ipvos-all_stream_Series.json')
VOD_JSON_PATH = os.path.join(CACHE_DIR, 'ipvos-all_stream_VOD.json')

session = CachedSession(cache_name='xtream_cache', backend='sqlite', expire_after=86400)

TCP_LIMIT = 500
SEM_LIMIT = 200
CHUNK_SIZE = 100
FILE_SEM_LIMIT = 100

# Global session for aiohttp
AIOHTTP_SESSION = None
ASYNC_LOOP = None

def log_to_kodi(msg):
    """Logs a message to Kodi's log and prints it to the console."""
    # Only log messages that are also shown as notifications or are critical debug info
    notification_msgs = [
        'Script started',
        'Loading and parsing M3U playlist...',
        'Processed',
        'Filtering entries by JSON data...',
        'Filtering out existing files...',
        'After filtering with JSON data & file existence',
        'No valid entries found',
        'No new entries found to add.',
        'Processing',
        'Summary: Added',
        'Total new files added:',
        'Total files removed:',
        'Total runtime:',
        'Cleanup of library folders complete.'
    ]
    if any(x in msg for x in notification_msgs) or "Error" in msg or "Fatal error" in msg or "Wrote" in msg or "Failed" in msg or "Skipping" in msg or "Using" in msg:
        xbmc.log(f"[m3utostrm] {msg}", xbmc.LOGINFO)
    print(f"[m3utostrm] {msg}")

def ensure_dir(dir_path):
    """Ensures that a directory exists, creating it if necessary."""
    if not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path)
            log_to_kodi(f"Created directory {dir_path}")
        except Exception as e:
            log_to_kodi(f"Could not create directory {dir_path}: {e}")

def confirm_and_delete(paths, m3u_basenames=None, sport_basenames=None, movies_dir=None, sport_dir=None):
    """
    Delete files/folders in paths that are not present in m3u_basenames (for .strm/.nfo files).
    Also, remove any sport entries (.strm/.nfo) from the movies directory if they match sport_basenames.
    """
    if not paths:
        return
    to_delete = []
    for p in paths:
        # Only delete .strm/.nfo files not in m3u_basenames
        base, ext = os.path.splitext(os.path.basename(p))
        if ext.lower() in ['.strm', '.nfo']:
            if m3u_basenames is not None and base.lower() not in m3u_basenames:
                to_delete.append(p)
        else:
            to_delete.append(p) # Always include non-.strm/.nfo files/folders for deletion if they are in paths

    # Remove any sport entries from movies_dir that are not supposed to be there
    if sport_basenames and movies_dir:
        for fname in os.listdir(movies_dir):
            base, ext = os.path.splitext(fname)
            if ext.lower() in ['.strm', '.nfo'] and base.lower() in sport_basenames:
                fpath = os.path.join(movies_dir, fname)
                if fpath not in to_delete: # Avoid adding duplicates
                    to_delete.append(fpath)

    # Remove any movie/tv entries from sport_dir that are not supposed to be there
    if m3u_basenames and sport_dir: # m3u_basenames here refers to non-sport content
        for root, dirs, files in os.walk(sport_dir):
            for fname in files:
                base, ext = os.path.splitext(fname)
                # If a file in sport_dir is not a sport file (i.e., it's a movie/tv file)
                if ext.lower() in ['.strm', '.nfo'] and base.lower() not in sport_basenames:
                    fpath = os.path.join(root, fname)
                    if fpath not in to_delete: # Avoid adding duplicates
                        to_delete.append(fpath)

    if not to_delete:
        log_to_kodi("No files to delete after filtering.")
        return

    summary = '\n'.join(to_delete)
    dialog = xbmcgui.Dialog()
    msg = f"The following files/folders will be deleted:\n\n{summary}\n\nDo you want to proceed?"
    ret = dialog.yesno('Confirm Deletion', msg)
    if ret:
        for p in to_delete:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
                elif os.path.isfile(p):
                    os.remove(p)
            except Exception as e:
                log_to_kodi(f"Failed to delete {p}: {e}")
        log_to_kodi(f"Deleted {len(to_delete)} files/folders.")
    else:
        log_to_kodi("User cancelled deletion.")


def sanitize(name):
    """
    Sanitizes a string to be used as a filename, removing invalid characters,
    leading numbers (e.g., "02. "), and normalizing spaces.
    """
    name = unidecode(name)
    # Remove leading numbers followed by a dot and space (e.g., "02. ")
    name = re.sub(r'^\d+\.\s*', '', name)
    # Remove characters illegal in Windows filenames
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    # Replace multiple spaces with a single space and strip leading/trailing spaces
    name = re.sub(r'\s+', ' ', name).strip()
    # Remove any remaining non-ASCII characters
    name = ''.join(c for c in name if ord(c) < 128)
    return name

def fetch_json_data_sync():
    """Fetches series and VOD data from the API and saves it to JSON cache files."""
    ensure_dir(CACHE_DIR)
    series_data = []
    vod_data = []
    try:
        log_to_kodi(f"Fetching Series data from {SERIES_API_URL}")
        series_resp = session.get(SERIES_API_URL)
        series_resp.raise_for_status()
        series_data = series_resp.json()
        original_series_count = len(series_data)
        series_data = [item for item in series_data if '#####' not in item.get('name', '')]
        log_to_kodi(f"Filtered out {original_series_count - len(series_data)} series entries with ##### in the title")
        with open(SERIES_JSON_PATH, 'w') as f:
            json.dump(series_data, f)
        log_to_kodi(f"Saved {len(series_data)} Series entries to {SERIES_JSON_PATH}")

        log_to_kodi(f"Fetching VOD data from {VOD_API_URL}")
        vod_resp = session.get(VOD_API_URL)
        vod_resp.raise_for_status()
        vod_data = vod_resp.json()
        original_vod_count = len(vod_data)
        vod_data = [item for item in vod_data if '#####' not in item.get('name', '')]
        log_to_kodi(f"Filtered out {original_vod_count - len(vod_data)} VOD entries with ##### in the title")
        with open(VOD_JSON_PATH, 'w') as f:
            json.dump(vod_data, f)
        log_to_kodi(f"Saved {len(vod_data)} VOD entries to {VOD_JSON_PATH}")
    except Exception as e:
        log_to_kodi(f"Error fetching JSON data: {e}")
    return series_data, vod_data

def filter_live_content(data_list):
    """Filters out live stream content from a list of data entries."""
    filtered_data = []
    for item in data_list:
        if item.get('stream_type', '').lower() != 'live':
            filtered_data.append(item)
    log_to_kodi(f"Filtered out {len(data_list) - len(filtered_data)} live stream entries from {len(data_list)} total")
    return filtered_data

def load_json_data():
    """Loads cached JSON data for series and VOD, or fetches it if not available or stale."""
    series_data = []
    vod_data = []
    try:
        if os.path.exists(SERIES_JSON_PATH):
            with open(SERIES_JSON_PATH, 'r') as f:
                series_data = json.load(f)
            log_to_kodi(f"Loaded {len(series_data)} Series entries from cache")
            original_series_count = len(series_data)
            series_data = [item for item in series_data if '#####' not in item.get('name', '')]
            log_to_kodi(f"Filtered out {original_series_count - len(series_data)} series entries with ##### in the title")
        if os.path.exists(VOD_JSON_PATH):
            with open(VOD_JSON_PATH, 'r') as f:
                vod_data = json.load(f)
            log_to_kodi(f"Loaded {len(vod_data)} VOD entries from cache")
            original_vod_count = len(vod_data)
            vod_data = [item for item in vod_data if '#####' not in item.get('name', '')]
            log_to_kodi(f"Filtered out {original_vod_count - len(vod_data)} VOD entries with ##### in the title")
    except Exception as e:
        log_to_kodi(f"Error loading cached JSON data: {e}")

    # If data is not loaded from cache, or if it's empty, fetch it
    if not series_data or not vod_data:
        series_data, vod_data = fetch_json_data_sync()

    series_data = filter_live_content(series_data)
    vod_data = filter_live_content(vod_data)
    log_to_kodi(f"After filtering out live streams: {len(series_data)} series and {len(vod_data)} VOD entries remain")
    return series_data, vod_data

async def fetch_m3u():
    """Fetches the M3U playlist, caches it, and parses its entries."""
    import time
    m3u_cache_path = os.path.join(CACHE_DIR, 'playlist.m3u')
    ensure_dir(CACHE_DIR)
    # Check if cache exists and is fresh (24h)
    if os.path.exists(m3u_cache_path):
        mtime = os.path.getmtime(m3u_cache_path)
        age = time.time() - mtime
        if age < 86400: # 24 hours in seconds
            log_to_kodi(f"Loading M3U playlist from cache: {m3u_cache_path}")
            with open(m3u_cache_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.read().splitlines()
            entries = parse_m3u(lines)
            log_to_kodi(f"Parsed {len(entries)} entries from cached M3U playlist")
            return entries
        else:
            log_to_kodi(f"M3U cache is older than 24h, re-downloading.")

    # Download and cache
    log_to_kodi(f"Fetching M3U playlist from {M3U_URL}")
    resp = session.get(M3U_URL, auth=(USERNAME, PASSWORD))
    resp.raise_for_status()
    with open(m3u_cache_path, 'w', encoding='utf-8') as f:
        f.write(resp.text)
    lines = resp.text.splitlines()
    entries = parse_m3u(lines)
    log_to_kodi(f"Parsed {len(entries)} entries from downloaded M3U playlist")
    return entries

def is_title_a_year(title):
    """Checks if a title string represents a year."""
    clean_title = title.strip()
    clean_title = re.sub(r'^\((\d{4})\)$', r'\1', clean_title) # Handle (YYYY) format
    return re.match(r'^\d{4}$', clean_title) is not None

def extract_title_and_year(title):
    """
    Extracts the main title and year from a string like "Movie Title (YYYY)".
    Returns (title, year).
    """
    if '(' in title and ')' in title:
        year_part = title.split('(')[-1].split(')')[0]
        if year_part.isdigit():
            return title.split('(')[0].strip(), year_part
    return title, ''

def create_filename(title, content_type, release_year=None):
    """
    Generates a clean filename for STRM files.
    Removes prefixes, sanitizes, appends year if available, and ensures a single .strm extension.
    """
    # Remove the prefix like "4K-EN - " by splitting on the first " - "
    if " - " in title:
        title = title.split(" - ", 1)[-1]

    # Remove any existing .strm extension before sanitizing and adding it back
    if title.lower().endswith('.strm'):
        title = title[:-5] # Remove .strm

    # Sanitize the title (this will also remove leading numbers like "02. ")
    title = sanitize(title)

    # Append the release year if available and not already part of the title
    if release_year and f"({release_year})" not in title:
        title = f"{title} ({release_year})"

    # Add the .strm extension
    title += '.strm'
    return title

def extract_stream_id_from_url(url):
    """Extracts the stream ID from an M3U URL."""
    # Example: "http://example.com/stream/12345.mkv" -> "12345"
    # Example: "http://example.com/stream/12345" -> "12345"
    match = re.search(r'/(\d+)(?:\.[^/]*)?$', url)
    if match:
        return match.group(1)
    return None

def remove_non_ascii(obj):
    """Recursively remove non-ASCII characters from all strings in a dict/list/str structure."""
    if isinstance(obj, dict):
        return {remove_non_ascii(k): remove_non_ascii(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [remove_non_ascii(i) for i in obj]
    elif isinstance(obj, str):
        return unidecode(obj)
    else:
        return obj

def extract_series_name_from_url(url):
    """Extract the series name from a /series/ URL segment."""
    match = re.search(r'/series/([^/]+)/', url)
    if match:
        # Replace dots/underscores with spaces, remove extra symbols
        name = match.group(1)
        name = re.sub(r'[._]+', ' ', name)
        name = re.sub(r'[^\w\s-]', '', name)
        return name.strip()
    return None

def parse_m3u(lines):
    """Parses M3U playlist lines into a list of entry dictionaries."""
    entries = []
    excluded_hashtag_count = 0
    extinf_pat = re.compile(r'#EXTINF:-1\s+(?P<attrs>.*?),(?P<title>.*)')
    tvg_group_pat = re.compile(r'tvg-group="([^"]*)"')
    group_title_pat = re.compile(r'group-title="([^"]*)"')
    stream_id_pat = re.compile(r'stream-id="([^"]*)"')
    tvg_id_pat = re.compile(r'tvg-id="([^"]*)"')
    tvg_name_pat = re.compile(r'tvg-name="([^"]*)"') # Added tvg_name pattern

    for i, line in enumerate(lines):
        if line.startswith('#EXTINF'):
            try:
                m = extinf_pat.search(line)
                if not m:
                    continue

                title = unidecode(m.group('title')).strip() if m else 'Unknown'
                attrs = m.group('attrs') if m else ''

                if '#####' in title:
                    excluded_hashtag_count += 1
                    continue

                # Ensure the next line is a URL and not another #EXTINF
                if i + 1 >= len(lines) or lines[i+1].startswith('#'):
                    continue
                url = lines[i+1].strip()
                if not url or url.startswith('#'):
                    continue

                # Extract stream_id from URL first (more reliable for movies/VOD)
                stream_id = extract_stream_id_from_url(url)

                # Fallback to attributes if URL extraction failed
                if not stream_id:
                    stream_id_match = stream_id_pat.search(attrs)
                    tvg_id_match = tvg_id_pat.search(attrs)
                    if stream_id_match:
                        stream_id = stream_id_match.group(1)
                    elif tvg_id_match:
                        stream_id = tvg_id_match.group(1)
                    elif 'id=' in url: # Original 'id=' check
                        id_match = re.search(r'id=(\d+)', url)
                        if id_match:
                            stream_id = id_match.group(1)

                group_title_match = group_title_pat.search(attrs)
                tvg_group_match = tvg_group_pat.search(attrs)
                group = ""
                if group_title_match:
                    group = group_title_match.group(1)
                elif tvg_group_match:
                    group = tvg_group_match.group(1)

                # Extract tvg-name for sports filename, fallback to title
                tvg_name_match = tvg_name_pat.search(attrs)
                tvg_name = tvg_name_match.group(1) if tvg_name_match else title

                content_type = "unknown"
                sport_category = None

                # --- Determine content type: TV first ---
                if 'series' in group.lower() or 'show' in group.lower() or '/series/' in url.lower() or 'series' in url.lower():
                    content_type = "tv"
                # --- Sports detection: if SOCCER in group and not TV ---
                elif 'soccer' in group.lower():
                    content_type = "sport"
                    match = re.search(r'SOCCER\s+([\w\- ]+)', group, re.IGNORECASE)
                    if match:
                        sport_category = match.group(1).strip()
                    log_to_kodi(f"Identified SPORT entry: title={title}, group={group}, category={sport_category}, tvg_name={tvg_name}")
                # --- Movie detection ---
                elif 'movie' in group.lower() or 'vod' in url.lower() or '/movie/' in url.lower() or 'movie' in url.lower():
                    content_type = "movie"
                else:
                    content_type = "unknown"

                # --- Improved TV show detection fallback for title ---
                if content_type == "tv":
                    # If title is empty, generic, or looks like a filename, fallback to URL extraction
                    fallback_needed = not title or title.lower() in ("unknown", "series", "tv show") or re.match(r'^s\d+e\d+', title, re.I)
                    if fallback_needed:
                        extracted = extract_series_name_from_url(url)
                        if extracted:
                            title = extracted # Use extracted name as the primary title for TV shows

                # Use create_filename to generate the safe filename for the entry
                # Pass original title and type, year will be handled if present in title
                clean_filename = create_filename(title, content_type)

                entry_dict = {
                    'title': title,
                    'url': url,
                    'safe': clean_filename, # This field now holds the correctly formatted filename
                    'type': content_type,
                    'group': group,
                    'stream_id': stream_id,
                    'original_title': title, # Keep original title for potential metadata fetching
                    'tvg_name': tvg_name # Store tvg_name for sports entries
                }
                if content_type == "sport":
                    entry_dict['sport_category'] = sport_category
                    log_to_kodi(f"Adding sport entry: {entry_dict}")
                entries.append(entry_dict)
            except Exception as e:
                log_to_kodi(f"Error parsing entry at line {i}: {e}")
    log_to_kodi(f"Excluded {excluded_hashtag_count} entries with ##### in the title")
    return entries

def filter_entries_by_json(entries, series_data, vod_data):
    """Filters M3U entries based on matching IDs or titles in JSON data, and enriches entries."""
    filtered_entries = []
    excluded_hashtag_count = 0
    # Create maps for quicker lookup by stream_id
    series_map = {str(item['series_id']): item for item in series_data if item.get('series_id')}
    vod_map = {str(item['stream_id']): item for item in vod_data if item.get('stream_id')}
    log_to_kodi(f"Found {len(series_map)} unique series IDs and {len(vod_map)} unique VOD IDs in JSON files")

    # Create maps for quicker lookup by title (for fuzzy matching fallback)
    series_titles_map = {item.get('name', '').lower(): item for item in series_data if item.get('name')}
    vod_titles_map = {item.get('name', '').lower(): item for item in vod_data if item.get('name')}

    id_matches = 0
    title_matches = 0

    for entry in entries:
        if entry.get('type') == 'sport':
            filtered_entries.append(entry) # Keep sports entries as is
            continue

        if '#####' in entry['title']:
            excluded_hashtag_count += 1
            continue

        matched_data = None
        stream_id = entry.get('stream_id')

        # Prioritize matching by stream_id
        if stream_id:
            if entry['type'] == 'tv' and stream_id in series_map:
                matched_data = series_map[stream_id]
            elif entry['type'] == 'movie' and stream_id in vod_map:
                matched_data = vod_map[stream_id]

        if matched_data:
            id_matches += 1
            # Enrich the entry with TMDB ID and other relevant data from the matched JSON entry
            entry['tmdb_id'] = matched_data.get('tmdb') # Add tmdb_id from JSON
            entry['json_name'] = matched_data.get('name') # Add the name from JSON, often cleaner
            # entry['json_release_date'] = matched_data.get('added') # Can add other fields if needed
            filtered_entries.append(entry)
            continue # Move to next entry if already matched by ID

        # If not matched by ID, try matching by title (fuzzy match)
        title_lower = entry['title'].lower()
        if entry['type'] == 'tv':
            for series_title, s_data in series_titles_map.items():
                if (series_title and title_lower and
                    (series_title in title_lower or title_lower in series_title)):
                    matched_data = s_data
                    title_matches += 1
                    break
        elif entry['type'] == 'movie':
            for vod_title, v_data in vod_titles_map.items():
                if (vod_title and title_lower and
                    (vod_title in title_lower or title_lower in vod_title)):
                    matched_data = v_data
                    title_matches += 1
                    break

        if matched_data:
            # Enrich the entry even if matched by title
            entry['tmdb_id'] = matched_data.get('tmdb')
            entry['json_name'] = matched_data.get('name')
            filtered_entries.append(entry)

    if excluded_hashtag_count > 0:
        log_to_kodi(f"Excluded an additional {excluded_hashtag_count} entries with ##### in the title during JSON matching")
    log_to_kodi(f"Matched {id_matches} entries by ID and {title_matches} by title")
    log_to_kodi(f"Filtered to {len(filtered_entries)} total entries that match JSON data")
    return filtered_entries

# ==== BEGIN: FILTER ENTRIES ALREADY EXISTING IN FILESYSTEM ====

def get_existing_movie_filenames(movies_dir):
    """Gets a set of existing movie filenames (base name without .strm) in the movies directory."""
    existing = set()
    if not os.path.exists(movies_dir):
        return existing
    for fname in os.listdir(movies_dir):
        if fname.lower().endswith('.strm'):
            base = os.path.splitext(fname)[0]
            existing.add(base.lower())
    return existing

def get_existing_tv_filenames(tvshows_dir):
    """Gets a set of existing TV episode filenames (base name without .strm) in the TV shows directory."""
    existing = set()
    if not os.path.exists(tvshows_dir):
        return existing
    for root, dirs, files in os.walk(tvshows_dir):
        for fname in files:
            if fname.lower().endswith('.strm'):
                base = os.path.splitext(fname)[0]
                existing.add(base.lower())
    return existing

def get_existing_sport_filenames(sport_dir):
    """Gets a set of existing sport filenames (base name without .strm) in the sports directory."""
    existing = set()
    if not os.path.exists(sport_dir):
        return existing
    for root, dirs, files in os.walk(sport_dir):
        for fname in files:
            if fname.lower().endswith('.strm'):
                base = os.path.splitext(fname)[0]
                existing.add(base.lower())
    return existing

def filter_entries_that_exist(entries, movies_dir, tvshows_dir):
    """Filters out entries that already exist as STRM files in the library directories."""
    movie_existing = get_existing_movie_filenames(movies_dir)
    tv_existing = get_existing_tv_filenames(tvshows_dir)
    sport_existing = get_existing_sport_filenames(SPORT_DIR) # Get existing sport files
    filtered = []
    skipped = 0
    for entry in entries:
        if entry['type'] == 'movie':
            # Use create_filename to get the expected filename for comparison
            fn = create_filename(entry['title'], entry['type'])
            # Remove the .strm extension for comparison with existing base names
            fn_base = os.path.splitext(fn)[0].lower()
            if fn_base in movie_existing:
                skipped += 1
                continue
        elif entry['type'] == 'tv':
            show_name, year = extract_title_and_year(entry['title'])
            show_name = sanitize(show_name) # Ensure show_name is sanitized for comparison
            season, episode = extract_season_episode(entry['original_title'])
            if not (season and episode):
                season, episode = extract_season_episode(entry['safe']) # entry['safe'] should be clean now

            if season and episode:
                # Construct the expected TV episode filename for comparison
                tvfn = kodi_tv_episode_filename(show_name, year, season, episode, "strm")
                tvfn_base = os.path.splitext(tvfn)[0].lower()
                if tvfn_base in tv_existing:
                    skipped += 1
                    continue
            else:
                # Fallback for TV shows without season/episode info (e.g., show folder STRM)
                folder_name = f"{show_name}{f' ({year})' if year else ''}"
                fallback_fn = sanitize(folder_name) # Ensure fallback is sanitized
                # Compare with existing TV show folder names or generic TV show strms
                if fallback_fn.lower() in tv_existing: # This might need more robust checking for show folders
                    skipped += 1
                    continue
        elif entry['type'] == 'sport': # Handle existing sport files
            # For sports, the filename is derived from tvg_name
            filename = entry.get('tvg_name', entry['title'])
            filename = re.sub(r'^SOC\s*-\s*', '', filename, flags=re.IGNORECASE)
            filename = sanitize(filename)
            if not filename:
                filename = 'Unknown'
            fn_base = os.path.splitext(f"{filename}.strm")[0].lower()
            if fn_base in sport_existing:
                skipped += 1
                continue
        filtered.append(entry)
    log_to_kodi(f"Filtered out {skipped} entries that already exist in library folders.")
    return filtered

# ==== END: FILTER ENTRIES ALREADY EXISTING IN FILESYSTEM ====

async def fetch_movie_metadata(title, session, sem: Semaphore, tmdb_id_from_json=None):
    """
    Fetches movie metadata from TMDB. Prioritizes using tmdb_id_from_json if provided,
    otherwise falls back to searching by title with fuzzy matching.
    """
    movie_id = None
    if tmdb_id_from_json:
        movie_id = tmdb_id_from_json
        log_to_kodi(f"Fetching movie metadata using TMDB ID from JSON: {movie_id}")
    else:
        clean_title, year = extract_title_and_year(title)
        search_query = clean_title
        is_year_title = is_title_a_year(clean_title)
        url = 'https://api.themoviedb.org/3/search/movie'
        params = {'api_key': TMDB_API_KEY, 'query': search_query}
        if year and not is_year_title:
            params['year'] = year

        async with sem:
            async with session.get(url, params=params, timeout=30) as r:
                if r.status == 200:
                    data = await r.json()
                    results = data.get('results', [])
                    if results:
                        movie_id = results[0].get('id')
                    else:
                        # Fuzzy match fallback: Try again without year restriction
                        params.pop('year', None)
                        async with session.get(url, params=params, timeout=30) as r2:
                            if r2.status == 200:
                                data2 = await r2.json()
                                results2 = data2.get('results', [])
                                if results2:
                                    # Perform fuzzy match on titles
                                    choices = {m['title']: m for m in results2 if 'title' in m}
                                    match, score, _ = process.extractOne(clean_title, list(choices.keys()), scorer=fuzz.token_sort_ratio)
                                    if score >= 85: # A score of 85 or higher is considered a good match
                                        movie_id = choices[match]['id']
                                    else:
                                        log_to_kodi(f"No good fuzzy match for movie title: {clean_title}")
                                        return {} # No good fuzzy match
                                else:
                                    log_to_kodi(f"No search results for movie title: {clean_title} even after removing year.")
                                    return {} # No results even without year
                            else:
                                log_to_kodi(f"Failed to fetch movie search results without year for: {clean_title}. Status: {r2.status}")
                                return {} # Failed second search
                else:
                    log_to_kodi(f"Failed to fetch movie search results for: {clean_title}. Status: {r.status}")
                    return {} # Failed initial search

    if not movie_id:
        log_to_kodi(f"No TMDB ID found for movie: {title} (after search or from JSON).")
        return {}

    # Fetch full details for the matched movie
    details_url = f'https://api.themoviedb.org/3/movie/{movie_id}'
    details_params = {'api_key': TMDB_API_KEY, 'append_to_response': 'credits,external_ids,release_dates'}
    async with sem:
        async with session.get(details_url, params=details_params, timeout=30) as r:
            if r.status == 200:
                log_to_kodi(f"Successfully fetched movie details for TMDB ID: {movie_id}")
                return await r.json()
            else:
                log_to_kodi(f"Failed to fetch movie details for TMDB ID: {movie_id}. Status: {r.status}")
                return {}

async def fetch_tv_metadata(title, session, sem: Semaphore, tmdb_id_from_json=None):
    """
    Fetches TV show metadata from TMDB. Prioritizes using tmdb_id_from_json if provided,
    otherwise falls back to searching by title with fuzzy matching.
    """
    tmdb_id = None
    if tmdb_id_from_json:
        tmdb_id = tmdb_id_from_json
        log_to_kodi(f"Fetching TV metadata using TMDB ID from JSON: {tmdb_id}")
    else:
        clean_title, year = extract_title_and_year(title)
        search_query = clean_title
        is_year_title = is_title_a_year(clean_title)

        api_key = TMDB_API_KEY
        tmdb_bearer = ADDON.getSetting('tmdb_bearer_token') if hasattr(ADDON, 'getSetting') else None

        search_url = 'https://api.themoviedb.org/3/search/tv'
        search_params = {'query': search_query}
        if api_key:
            search_params['api_key'] = api_key
        if year and not is_year_title:
            search_params['first_air_date_year'] = year

        headers = {}
        if tmdb_bearer:
            headers['Authorization'] = f'Bearer {tmdb_bearer}'
            search_params.pop('api_key', None) # Remove api_key if bearer token is used

        async with sem:
            async with session.get(search_url, params=search_params, headers=headers, timeout=30) as r:
                if r.status != 200:
                    log_to_kodi(f"Failed to fetch TV search results for: {clean_title}. Status: {r.status}")
                    return {}
                data = await r.json()
                results = data.get('results', [])
                if not results:
                    # Fuzzy match fallback: Try again without year restriction
                    search_params.pop('first_air_date_year', None)
                    async with session.get(search_url, params=search_params, headers=headers, timeout=30) as r2:
                        if r2.status == 200:
                            data2 = await r2.json()
                            results2 = data2.get('results', [])
                            if results2:
                                choices = {m['name']: m for m in results2 if 'name' in m}
                                match, score, _ = process.extractOne(clean_title, list(choices.keys()), scorer=fuzz.token_sort_ratio)
                                if score >= 85:
                                    tmdb_id = choices[match]['id']
                                else:
                                    log_to_kodi(f"No good fuzzy match for TV title: {clean_title}")
                                    return {}
                            else:
                                log_to_kodi(f"No search results for TV title: {clean_title} even after removing year.")
                                return {}
                        else:
                            log_to_kodi(f"Failed to fetch TV search results without year for: {clean_title}. Status: {r2.status}")
                            return {}
                else:
                    tmdb_id = results[0].get('id')

    if not tmdb_id:
        log_to_kodi(f"No TMDB ID found for TV show: {title} (after search or from JSON).")
        return {}

    # Fetch full details for the matched TV show
    details_url = f'https://api.themoviedb.org/3/tv/{tmdb_id}'
    details_params = {'append_to_response': 'credits,external_ids,content_ratings,images'}
    if api_key and not tmdb_bearer:
        details_params['api_key'] = api_key

    headers = {}
    if tmdb_bearer:
        headers['Authorization'] = f'Bearer {tmdb_bearer}'
        details_params.pop('api_key', None)

    async with sem:
        async with session.get(details_url, params=details_params, headers=headers, timeout=30) as r:
            if r.status != 200:
                log_to_kodi(f"Failed to fetch TV details for TMDB ID: {tmdb_id}. Status: {r.status}")
                return {}
            meta = await r.json()
            log_to_kodi(f"Successfully fetched TV details for TMDB ID: {tmdb_id}")
            return meta

async def fetch_episode_metadata(tv_id, season, episode, session, sem):
    """Fetches episode-specific metadata from TMDB."""
    api_key = TMDB_API_KEY
    tmdb_bearer = ADDON.getSetting('tmdb_bearer_token') if hasattr(ADDON, 'getSetting') else None

    url = f'https://api.themoviedb.org/3/tv/{tv_id}/season/{season}/episode/{episode}'
    params = {'append_to_response': 'credits,external_ids,images,content_ratings'} # Added images for stills
    if api_key and not tmdb_bearer:
        params['api_key'] = api_key

    headers = {}
    if tmdb_bearer:
        headers['Authorization'] = f'Bearer {tmdb_bearer}'
        params.pop('api_key', None)

    async with sem:
        async with session.get(url, params=params, headers=headers, timeout=30) as r:
            if r.status != 200:
                return {}
            return await r.json()

def meta_to_nfo(meta, entry_type):
    """Generates NFO content (XML) for movies or TV shows based on metadata."""
    from xml.etree.ElementTree import Element, SubElement, tostring

    meta = remove_non_ascii(meta) # Ensure all strings are ASCII for NFO compatibility
    if entry_type == 'movie':
        root = Element('movie')
        SubElement(root, 'title').text = meta.get('title', '')
        SubElement(root, 'originaltitle').text = meta.get('original_title', meta.get('title', ''))
        sorttitle = meta.get('title', '')
        if meta.get('belongs_to_collection'):
            sorttitle = meta['belongs_to_collection'].get('name', sorttitle)
        SubElement(root, 'sorttitle').text = sorttitle

        ratings = SubElement(root, 'ratings')
        imdb_id = meta.get('external_ids', {}).get('imdb_id')
        if imdb_id:
            rating = SubElement(ratings, 'rating', name='imdb', max='10', default='true')
            SubElement(rating, 'value').text = str(meta.get('vote_average', ''))
            SubElement(rating, 'votes').text = str(meta.get('vote_count', ''))
        rating_tmdb = SubElement(ratings, 'rating', name='themoviedb', max='10')
        SubElement(rating_tmdb, 'value').text = str(meta.get('vote_average', ''))
        SubElement(rating_tmdb, 'votes').text = str(meta.get('vote_count', ''))
        rating_trakt = SubElement(ratings, 'rating', name='trakt', max='10')
        SubElement(rating_trakt, 'value').text = '' # Trakt rating not fetched
        SubElement(rating_trakt, 'votes').text = ''
        SubElement(root, 'userrating').text = str(meta.get('vote_average', '')) # Using TMDB average as user rating
        SubElement(root, 'top250').text = '0' # Not fetched
        SubElement(root, 'outline').text = '' # Not directly available
        SubElement(root, 'plot').text = meta.get('overview', '')
        SubElement(root, 'tagline').text = meta.get('tagline', '')
        SubElement(root, 'runtime').text = str(meta.get('runtime', ''))

        poster_path = meta.get('poster_path')
        backdrop_path = meta.get('backdrop_path')
        if poster_path:
            SubElement(root, 'thumb', spoof='', cache='', aspect='poster', preview=f"https://image.tmdb.org/t/p/original{poster_path}").text = f"https://image.tmdb.org/t/p/original{poster_path}"
        if backdrop_path:
            SubElement(root, 'thumb', spoof='', cache='', aspect='landscape', preview=f"https://image.tmdb.org/t/p/original{backdrop_path}").text = f"https://image.tmdb.org/t/p/original{backdrop_path}"
        if backdrop_path:
            fanart = SubElement(root, 'fanart')
            SubElement(fanart, 'thumb', colors='', preview=f"https://image.tmdb.org/t/p/w780{backdrop_path}").text = f"https://image.tmdb.org/t/p/original{backdrop_path}"

        mpaa = ''
        for rel in meta.get('release_dates', {}).get('results', []):
            if rel.get('iso_3166_1') == 'US':
                for r in rel.get('release_dates', []):
                    if r.get('certification'):
                        mpaa = r.get('certification')
                        break
        SubElement(root, 'mpaa').text = mpaa
        SubElement(root, 'playcount').text = '0'
        SubElement(root, 'lastplayed').text = ''
        SubElement(root, 'id').text = str(meta.get('id', ''))
        if imdb_id:
            SubElement(root, 'uniqueid', type='imdb').text = imdb_id
        SubElement(root, 'uniqueid', type='tmdb', default='true').text = str(meta.get('id', ''))

        genres = meta.get('genres', [])
        if genres:
            for g in genres:
                SubElement(root, 'genre').text = g.get('name', '')
        countries = meta.get('production_countries', [])
        for c in countries:
            SubElement(root, 'country').text = c.get('name', '')

        if meta.get('belongs_to_collection'):
            set_el = SubElement(root, 'set')
            SubElement(set_el, 'name').text = meta['belongs_to_collection'].get('name', '')
            SubElement(set_el, 'overview').text = '' # Overview not fetched for collection

        crew = meta.get('credits', {}).get('crew', [])
        writers = [w.get('name') for w in crew if w.get('job', '').lower() == 'writer']
        for w in writers:
            SubElement(root, 'credits').text = w
        directors = [d.get('name') for d in crew if d.get('job', '').lower() == 'director']
        for d in directors:
            SubElement(root, 'director').text = d

        SubElement(root, 'premiered').text = meta.get('release_date', '')
        SubElement(root, 'year').text = (meta.get('release_date') or '')[:4]
        SubElement(root, 'status').text = '' # Not directly available for movies
        SubElement(root, 'code').text = '' # Not directly available
        SubElement(root, 'aired').text = '' # Use premiered for movies

        studios = meta.get('production_companies', [])
        for s in studios:
            SubElement(root, 'studio').text = s.get('name', '')
        SubElement(root, 'trailer').text = '' # Not directly available

        cast = meta.get('credits', {}).get('cast', [])
        for idx, actor in enumerate(cast):
            actor_el = SubElement(root, 'actor')
            SubElement(actor_el, 'name').text = actor.get('name', '')
            SubElement(actor_el, 'role').text = actor.get('character', '')
            SubElement(actor_el, 'order').text = str(idx)
            if actor.get('profile_path'):
                SubElement(actor_el, 'thumb').text = f"https://image.tmdb.org/t/p/original{actor['profile_path']}"

        # Resume (placeholder)
        resume = SubElement(root, 'resume')
        SubElement(resume, 'position').text = '0.000000'
        SubElement(resume, 'total').text = '0.000000'
        # Date added (placeholder: current date)
        SubElement(root, 'dateadded').text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    else: # entry_type == 'tv' (for tvshow.nfo)
        root = Element('tvshow')
        SubElement(root, 'title').text = meta.get('name', '')
        SubElement(root, 'originaltitle').text = meta.get('original_name', meta.get('name', ''))
        SubElement(root, 'showtitle').text = meta.get('name', '') # Redundant but common in NFOs

        ratings = SubElement(root, 'ratings')
        imdb_id = meta.get('external_ids', {}).get('imdb_id')
        tvdb_id = meta.get('external_ids', {}).get('tvdb_id')
        tmdb_id = meta.get('id')

        rating_imdb = SubElement(ratings, 'rating', name='imdb', max='10', default='true')
        SubElement(rating_imdb, 'value').text = '' # IMDB rating not fetched for TV shows
        SubElement(rating_imdb, 'votes').text = ''

        rating_tmdb = SubElement(ratings, 'rating', name='tmdb', max='10')
        SubElement(rating_tmdb, 'value').text = str(meta.get('vote_average', ''))
        SubElement(rating_tmdb, 'votes').text = str(meta.get('vote_count', ''))

        rating_trakt = SubElement(ratings, 'rating', name='trakt', max='10')
        SubElement(rating_trakt, 'value').text = ''
        SubElement(rating_trakt, 'votes').text = ''
        SubElement(root, 'userrating').text = str(meta.get('vote_average', ''))
        SubElement(root, 'top250').text = '0'

        SubElement(root, 'season').text = str(meta.get('number_of_seasons', ''))
        SubElement(root, 'episode').text = str(meta.get('number_of_episodes', ''))
        SubElement(root, 'displayseason').text = '-1' # Kodi default
        SubElement(root, 'displayepisode').text = '-1' # Kodi default
        SubElement(root, 'outline').text = ''
        SubElement(root, 'plot').text = meta.get('overview', '')
        SubElement(root, 'tagline').text = meta.get('tagline', '')
        # episode_run_time is a list, take the first element if available
        runtime = meta.get('episode_run_time', ['0'])[0] if meta.get('episode_run_time') else '0'
        SubElement(root, 'runtime').text = str(runtime)

        poster_path = meta.get('poster_path')
        backdrop_path = meta.get('backdrop_path')
        logo_path = ''
        if meta.get('images'):
            logos = meta['images'].get('logos', [])
            if logos:
                logo_path = logos[0].get('file_path', '')

        if backdrop_path:
            SubElement(root, 'thumb', spoof='', cache='', aspect='landscape', preview=f"https://image.tmdb.org/t/p/w780{backdrop_path}").text = f"https://image.tmdb.org/t/p/original{backdrop_path}"
        if logo_path:
            SubElement(root, 'thumb', spoof='', cache='', aspect='logos', preview=f"https://image.tmdb.org/t/p/w780{logo_path}").text = f"https://image.tmdb.org/t/p/original{logo_path}"
        if poster_path:
            SubElement(root, 'thumb', spoof='', cache='', aspect='poster', preview=f"https://image.tmdb.org/t/p/w780{poster_path}").text = f"https://image.tmdb.org/t/p/original{poster_path}"

        # Season posters
        for season_data in meta.get('seasons', []):
            s_poster = season_data.get('poster_path')
            s_num = season_data.get('season_number')
            if s_poster and s_num is not None:
                SubElement(root, 'thumb', spoof='', cache='', season=str(s_num), type='season', aspect='poster', preview=f"https://image.tmdb.org/t/p/w780{s_poster}").text = f"https://image.tmdb.org/t/p/original{s_poster}"

        # Fanart (multiple images)
        fanart = SubElement(root, 'fanart')
        fanart_paths = []
        if meta.get('images'):
            fanart_paths = [img['file_path'] for img in meta['images'].get('backdrops', [])[:2] if img.get('file_path')]
        elif backdrop_path:
            fanart_paths = [backdrop_path] # Fallback to main backdrop if no specific fanart
        for fpath in fanart_paths:
            SubElement(fanart, 'thumb', colors='', preview=f"https://image.tmdb.org/t/p/original{fpath}").text = f"https://image.tmdb.org/t/p/original{fpath}"

        mpaa = ''
        for rel in meta.get('content_ratings', {}).get('results', []):
            if rel.get('iso_3166_1') == 'US' and rel.get('rating'):
                mpaa = f"US:{rel['rating']}"
                break
            elif rel.get('iso_3166_1') and rel.get('rating'): # Use first available if US not found
                mpaa = f"{rel['iso_3166_1']}:{rel['rating']}"
        SubElement(root, 'mpaa').text = mpaa
        SubElement(root, 'playcount').text = '0'
        SubElement(root, 'lastplayed').text = ''
        SubElement(root, 'id').text = str(tmdb_id or '')

        if imdb_id:
            SubElement(root, 'uniqueid', type='imdb').text = imdb_id
        if tmdb_id:
            SubElement(root, 'uniqueid', type='tmdb', default='true').text = str(tmdb_id)
        if tvdb_id:
            SubElement(root, 'uniqueid', type='tvdb').text = str(tvdb_id)

        genres = meta.get('genres', [])
        if genres:
            for g in genres:
                SubElement(root, 'genre').text = g.get('name', '')

        premiered = meta.get('first_air_date', '')
        SubElement(root, 'premiered').text = premiered
        SubElement(root, 'year').text = premiered[:4] if premiered else ''
        SubElement(root, 'status').text = meta.get('status', '')
        SubElement(root, 'code').text = ''
        SubElement(root, 'aired').text = '' # Use premiered for TV shows

        studios = meta.get('networks', [])
        for s in studios:
            SubElement(root, 'studio').text = s.get('name', '')
        SubElement(root, 'trailer').text = ''

        cast = meta.get('credits', {}).get('cast', [])
        for idx, actor in enumerate(cast):
            actor_el = SubElement(root, 'actor')
            SubElement(actor_el, 'name').text = actor.get('name', '')
            SubElement(actor_el, 'role').text = actor.get('character', '')
            SubElement(actor_el, 'order').text = str(idx)
            if actor.get('profile_path'):
                SubElement(actor_el, 'thumb').text = f"https://image.tmdb.org/t/p/original{actor['profile_path']}"

        # Named seasons (e.g., "Season 1: The Beginning")
        for season_data in meta.get('seasons', []):
            if season_data.get('season_number') is not None and season_data.get('name'):
                namedseason = SubElement(root, 'namedseason')
                namedseason.set('number', str(season_data['season_number']))
                namedseason.text = season_data['name']

        resume = SubElement(root, 'resume')
        SubElement(resume, 'position').text = '0.000000'
        SubElement(resume, 'total').text = '0.000000'
        SubElement(root, 'dateadded').text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Return the XML as a string
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n' + tostring(root, encoding='utf-8').decode()

def episode_meta_to_nfo(meta, season=None, episode=None, show_meta=None):
    """Generates NFO content (XML) for individual TV episodes based on metadata."""
    from xml.etree.ElementTree import Element, SubElement, tostring

    meta = remove_non_ascii(meta)
    if show_meta:
        show_meta = remove_non_ascii(show_meta)

    root = Element('episodedetails')
    SubElement(root, 'title').text = meta.get('name', '') or meta.get('title', '')

    showtitle = ''
    if show_meta and show_meta.get('name'):
        showtitle = show_meta.get('name')
    elif meta.get('show', {}).get('name'): # Fallback if show_meta not passed
        showtitle = meta['show']['name']
    SubElement(root, 'showtitle').text = showtitle

    ratings = SubElement(root, 'ratings')
    imdb_id = meta.get('external_ids', {}).get('imdb_id')
    tmdb_id = meta.get('id')
    tvdb_id = meta.get('external_ids', {}).get('tvdb_id')

    rating_imdb = SubElement(ratings, 'rating', name='imdb', max='10', default='true')
    SubElement(rating_imdb, 'value').text = str(meta.get('vote_average', ''))
    SubElement(rating_imdb, 'votes').text = str(meta.get('vote_count', ''))

    rating_tmdb = SubElement(ratings, 'rating', name='tmdb', max='10')
    SubElement(rating_tmdb, 'value').text = str(meta.get('vote_average', ''))
    SubElement(rating_tmdb, 'votes').text = str(meta.get('vote_count', ''))

    rating_trakt = SubElement(ratings, 'rating', name='trakt', max='10')
    SubElement(rating_trakt, 'value').text = ''
    SubElement(rating_trakt, 'votes').text = ''
    SubElement(root, 'userrating').text = '0'
    SubElement(root, 'top250').text = '0'

    if season is not None:
        SubElement(root, 'season').text = str(season)
    if episode is not None:
        SubElement(root, 'episode').text = str(episode)
    SubElement(root, 'displayseason').text = '-1'
    SubElement(root, 'displayepisode').text = '-1'
    SubElement(root, 'outline').text = ''
    SubElement(root, 'plot').text = meta.get('overview', '')
    SubElement(root, 'tagline').text = ''

    runtime = meta.get('runtime') or meta.get('episode_run_time') or 0
    if isinstance(runtime, list):
        runtime = runtime[0] if runtime else 0
    SubElement(root, 'runtime').text = str(runtime)

    thumbs = []
    if meta.get('still_path'):
        thumbs.append(meta['still_path'])
    if meta.get('images'):
        thumbs += [img['file_path'] for img in meta['images'].get('stills', []) if img.get('file_path')]
    for t in thumbs[:2]: # Limit to 2 thumbs
        SubElement(root, 'thumb', spoof='', cache='', aspect='thumb', preview=f"https://image.tmdb.org/t/p/w780{t}").text = f"https://image.tmdb.org/t/p/original{t}"

    mpaa = ''
    for rel in meta.get('content_ratings', {}).get('results', []):
        if rel.get('iso_3166_1') == 'US' and rel.get('rating'):
            mpaa = f"US:{rel['rating']}"
            break
        elif rel.get('iso_3166_1') and rel.get('rating'):
            mpaa = f"{rel['iso_3166_1']}:{rel['rating']}"
    SubElement(root, 'mpaa').text = mpaa
    SubElement(root, 'playcount').text = '0'
    SubElement(root, 'lastplayed').text = ''
    SubElement(root, 'id').text = str(tmdb_id or '')

    if imdb_id:
        SubElement(root, 'uniqueid', type='imdb').text = imdb_id
    if tmdb_id:
        SubElement(root, 'uniqueid', type='tmdb', default='true').text = str(tmdb_id)
    if tvdb_id:
        SubElement(root, 'uniqueid', type='tvdb').text = str(tvdb_id)

    genres = []
    if show_meta and show_meta.get('genres'):
        genres = [g.get('name', '') for g in show_meta['genres']]
    for g in genres:
        SubElement(root, 'genre').text = g

    writers = meta.get('crew', [])
    credits = [w.get('name') for w in writers if w.get('job', '').lower() == 'writer']
    for w in credits:
        SubElement(root, 'credits').text = w
    directors = [d.get('name') for d in writers if d.get('job', '').lower() == 'director']
    for d in directors:
        SubElement(root, 'director').text = d

    premiered = meta.get('air_date', '') or meta.get('first_air_date', '')
    SubElement(root, 'premiered').text = premiered
    SubElement(root, 'year').text = premiered[:4] if premiered else ''
    SubElement(root, 'status').text = ''
    SubElement(root, 'code').text = ''
    SubElement(root, 'aired').text = premiered

    studios = []
    if show_meta and show_meta.get('networks'):
        studios = [s.get('name', '') for s in show_meta['networks']]
    for s in studios:
        SubElement(root, 'studio').text = s

    SubElement(root, 'trailer').text = ''

    # Fileinfo (placeholder, no streamdetails)
    fileinfo = SubElement(root, 'fileinfo')
    streamdetails = SubElement(fileinfo, 'streamdetails')
    video = SubElement(streamdetails, 'video')
    SubElement(video, 'codec').text = ''
    SubElement(video, 'aspect').text = ''
    SubElement(video, 'width').text = ''
    SubElement(video, 'height').text = ''
    SubElement(video, 'durationinseconds').text = ''
    SubElement(video, 'stereomode').text = '' # Not fetched
    audio = SubElement(streamdetails, 'audio')
    SubElement(audio, 'codec').text = ''
    SubElement(audio, 'language').text = ''
    SubElement(audio, 'channels').text = ''

    cast = meta.get('guest_stars', []) or meta.get('credits', {}).get('cast', [])
    for idx, actor in enumerate(cast):
        actor_el = SubElement(root, 'actor')
        SubElement(actor_el, 'name').text = actor.get('name', '')
        SubElement(actor_el, 'role').text = actor.get('character', '')
        SubElement(actor_el, 'order').text = str(idx)
        if actor.get('profile_path'):
            SubElement(actor_el, 'thumb').text = f"https://image.tmdb.org/t/p/original{actor['profile_path']}"

    resume = SubElement(root, 'resume')
    SubElement(resume, 'position').text = '0.000000'
    SubElement(resume, 'total').text = '0.000000'
    SubElement(root, 'dateadded').text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    return '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n' + tostring(root, encoding='utf-8').decode()

def extract_season_episode(title):
    """
    Extracts season and episode numbers from a title string using various patterns.
    Returns (season, episode) or (None, None).
    """
    patterns = [
        r"[Ss](\d{1,2})[\. _-]?[Ee](\d{1,2})", # S01E01, S1.E1, S01-E01
        r"(\d{1,2})x(\d{2})",                  # 1x01
        r"[Ss](\d{1,2})[ _.-]?Ep?\.?(\d{1,2})",# S01Ep01, S1 E1
        r"Season[ _]?(\d{1,2})[ _\-]+Ep(isode)?[ _]?(\d{1,2})" # Season 1 Episode 1
    ]
    for pat in patterns:
        m = re.search(pat, title, re.IGNORECASE) # Ignore case for patterns
        if m:
            try:
                # Handle patterns with 2 or 3 groups (e.g., Season X Episode Y)
                if len(m.groups()) == 2:
                    return int(m.group(1)), int(m.group(2))
                if len(m.groups()) == 3:
                    return int(m.group(1)), int(m.group(3))
            except ValueError: # Catch cases where conversion to int fails
                continue
    return None, None

def format_season_folder(season_num):
    """Formats a season number into a standard folder name (e.g., "Season 01")."""
    return f"Season {season_num:02d}"

def kodi_tv_episode_filename(showname, year, season, episode, ext, tmdb_id=''):
    """
    Generates a Kodi-compliant filename for a TV episode.
    Ensures correct formatting with season/episode numbers and extension.
    """
    base = f"{showname}"
    if year:
        base += f" ({year})"
    if tmdb_id:
        base += f" {{tmdb={tmdb_id}}}" # Kodi NFO matching tag
    base += f" S{season:02d}E{episode:02d}.{ext}"
    return base

async def process_batch(batch, directory, aio_sess, sem, file_sem):
    """Processes a batch of entries, creating directories and handling STRM/NFO files."""
    ensure_dir(directory)
    tasks = [handle_entry(e, directory, aio_sess, sem, file_sem) for e in batch]
    await asyncio.gather(*tasks)

async def handle_entry(entry, directory, aio_sess, sem, file_sem):
    """Handles a single M3U entry, fetching metadata and creating STRM/NFO files."""
    if not entry['title'].strip() or entry['safe'] == 'Unknown':
        log_to_kodi(f"Skipping entry with invalid title: {entry}")
        return

    if entry['type'] == 'sport':
        # Sports entries are handled by process_sports_entries, not here
        return

    if entry['type'] != 'tv': # Handle movies
        ensure_dir(directory)
        # Pass the tmdb_id_from_json if available in the entry
        meta = await fetch_movie_metadata(entry['title'], aio_sess, sem, entry.get('tmdb_id'))

        if meta and (meta.get('title') or meta.get('name')):
            movie_title = meta.get('title') or meta.get('name')
            release_year = (meta.get('release_date') or '')[:4] if meta.get('release_date') else None
            # create_filename now returns the full filename with .strm
            filename_with_ext = create_filename(movie_title, entry['type'], release_year)
            log_to_kodi(f"Using metadata-based filename: {filename_with_ext}")
        else:
            # Fallback to the 'safe' filename generated during M3U parsing
            # entry['safe'] should already be correctly formatted by create_filename in parse_m3u
            filename_with_ext = entry['safe']
            log_to_kodi(f"Using fallback filename from M3U: {filename_with_ext} (Metadata not found for NFO).")

        strm_path = os.path.join(directory, filename_with_ext)
        # NFO filename should have .nfo extension, replacing .strm
        nfo_path = os.path.join(directory, os.path.splitext(filename_with_ext)[0] + ".nfo")

        # Only create files if they do not exist
        if not os.path.exists(strm_path):
            try:
                async with file_sem:
                    async with aiofiles.open(strm_path, 'w') as f:
                        await f.write(entry['url'])
                        log_to_kodi(f"Wrote STRM file: {strm_path}")
            except Exception as e:
                log_to_kodi(f"Failed to write STRM file at {strm_path}: {e}")
                return # If STRM fails, no point in writing NFO

        else:
            log_to_kodi(f"STRM file already exists, skipping: {strm_path}")

        if meta and not os.path.exists(nfo_path):
            try:
                async with file_sem:
                    async with aiofiles.open(nfo_path, 'w') as f:
                        await f.write(meta_to_nfo(meta, entry['type']))
                        log_to_kodi(f"Wrote NFO file: {nfo_path}")
            except Exception as e:
                log_to_kodi(f"Failed to write NFO file at {nfo_path}: {e}")
        elif meta:
            log_to_kodi(f"NFO file already exists, skipping: {nfo_path}")
        return

    # Handle TV shows
    # Pass the tmdb_id_from_json if available in the entry
    meta = await fetch_tv_metadata(entry['title'], aio_sess, sem, entry.get('tmdb_id'))
    tmdb_id_for_filename = '' # Initialize for filename generation

    if meta and meta.get('name'):
        show_name = sanitize(meta['name']) # Sanitize show name from metadata
        year = (meta.get('first_air_date', '')[:4] if meta.get('first_air_date') else '')
        tmdb_id_for_filename = meta.get('id') # Use TMDB ID from fetched metadata for filename
        log_to_kodi(f"Using TMDB metadata show_name/year: {show_name}/{year} (TMDB ID: {tmdb_id_for_filename})")
    else:
        log_to_kodi(f"TMDB metadata not found for TV entry: {entry['title']}. Using fallback.")
        # Fallback: extract show name and year from the title, but remove season/episode info
        show_name, year = extract_title_and_year(entry['title'])
        show_name = sanitize(show_name) # Sanitize fallback show name
        # Remove trailing Sxx Exx or similar patterns from show_name to get clean show folder name
        show_name = re.sub(r'[ \-]*[Ss]\d{1,2}[ \-]*[Ee]\d{1,2}.*$', '', show_name, flags=re.IGNORECASE).strip()
        # tmdb_id_for_filename remains empty if no metadata found.
        log_to_kodi(f"Fallback show_name/year: {show_name}/{year}")

    if year:
        show_folder = os.path.join(TVSHOWS_DIR, f"{show_name} ({year})")
    else:
        show_folder = os.path.join(TVSHOWS_DIR, show_name)

    os.makedirs(show_folder, exist_ok=True) # Ensure show folder exists

    # Write tvshow.nfo at the show folder level if meta is available
    tvshow_nfo_path = os.path.join(show_folder, 'tvshow.nfo')
    if meta and not os.path.exists(tvshow_nfo_path):
        try:
            async with file_sem:
                async with aiofiles.open(tvshow_nfo_path, 'w') as f:
                    await f.write(meta_to_nfo(meta, 'tv'))
                    log_to_kodi(f"Wrote TV show NFO file: {tvshow_nfo_path}")
        except Exception as e:
            log_to_kodi(f"Failed to write TV show NFO file at {tvshow_nfo_path}: {e}")
    elif meta:
        log_to_kodi(f"TV show NFO file already exists, skipping: {tvshow_nfo_path}")

    season, episode = extract_season_episode(entry['original_title'])
    if not (season and episode):
        # If not found in original title, try the 'safe' title (which is already sanitized)
        season, episode = extract_season_episode(entry['safe'])

    if season is not None and episode is not None:
        season_folder = os.path.join(show_folder, format_season_folder(season))
        os.makedirs(season_folder, exist_ok=True)

        # Generate episode filename using kodi_tv_episode_filename
        # show_name is already sanitized at this point
        episode_filename = kodi_tv_episode_filename(show_name, year, season, episode, "strm", tmdb_id_for_filename)
        strm_path = os.path.join(season_folder, episode_filename)
        # NFO filename for episode
        nfo_filename = os.path.splitext(episode_filename)[0] + ".nfo"
        nfo_path = os.path.join(season_folder, nfo_filename)

        # Only create files if they do not exist
        if not os.path.exists(strm_path):
            try:
                async with file_sem:
                    async with aiofiles.open(strm_path, 'w') as f:
                        await f.write(entry['url'])
                    log_to_kodi(f"Wrote STRM file: {strm_path}")
            except Exception as e:
                log_to_kodi(f"Failed to write STRM file at {strm_path}: {e}")
        else:
            log_to_kodi(f"STRM file already exists, skipping: {strm_path}")

        # Fetch and write episode-specific NFO
        if meta and meta.get('id') and not os.path.exists(nfo_path):
            episode_meta = await fetch_episode_metadata(meta['id'], season, episode, aio_sess, sem)
            if episode_meta:
                try:
                    async with file_sem:
                        async with aiofiles.open(nfo_path, 'w') as f:
                            await f.write(episode_meta_to_nfo(episode_meta, season, episode, meta))
                        log_to_kodi(f"Wrote episode NFO file: {nfo_path}")
                except Exception as e:
                    log_to_kodi(f"Failed to write episode NFO file at {nfo_path}: {e}")
            else:
                log_to_kodi(f"Could not fetch episode metadata for {show_name} S{season:02d}E{episode:02d} (TMDB ID: {meta.get('id')}).")
        elif meta:
            log_to_kodi(f"Episode NFO file already exists, skipping: {nfo_path}")
    else:
        # This block handles TV entries where season/episode could not be extracted.
        # It creates a generic STRM and NFO directly in the show folder.
        log_to_kodi(f"Could not extract season/episode for TV entry: {entry['title']}. Creating fallback STRM/NFO.")
        fallback_fn = create_filename(show_name, entry['type'], year)
        strm_path = os.path.join(show_folder, fallback_fn)
        nfo_path = os.path.join(show_folder, os.path.splitext(fallback_fn)[0] + ".nfo")

        if not os.path.exists(strm_path):
            try:
                async with file_sem:
                    async with aiofiles.open(strm_path, 'w') as f:
                        await f.write(entry['url'])
                    log_to_kodi(f"Wrote fallback STRM file: {strm_path}")
            except Exception as e:
                log_to_kodi(f"Failed to write fallback STRM file at {strm_path}: {e}")
        else:
            log_to_kodi(f"Fallback STRM file already exists, skipping: {strm_path}")

        if meta and not os.path.exists(nfo_path):
            try:
                async with file_sem:
                    async with aiofiles.open(nfo_path, 'w') as f:
                        await f.write(meta_to_nfo(meta, "tv"))
                    log_to_kodi(f"Wrote fallback NFO file: {nfo_path}")
            except Exception as e:
                log_to_kodi(f"Failed to write fallback NFO file at {nfo_path}: {e}")
        elif meta:
            log_to_kodi(f"Fallback NFO file already exists, skipping: {nfo_path}")

async def process_sports_entries(sports_entries, sport_dir, file_sem):
    """
    For each unique sport_category, create a folder in sport_dir.
    For each entry, create a .strm file in the correct folder, named after tvg-name with 'SOC - ' removed.
    No .nfo files are created for sports entries.
    """
    log_to_kodi(f"Processing {len(sports_entries)} sports entries. sport_dir={sport_dir}")
    if not sports_entries:
        log_to_kodi("No sports entries to process.")
        return

    for entry in sports_entries:
        log_to_kodi(f"Handling sport entry: {entry.get('title', 'N/A')}")
        category = entry.get('sport_category', 'Other')
        folder = os.path.join(sport_dir, sanitize(category))
        ensure_dir(folder)

        # Remove 'SOC - ' from tvg_name if present, then sanitize
        filename = entry.get('tvg_name', entry['title'])
        filename = re.sub(r'^SOC\s*-\s*', '', filename, flags=re.IGNORECASE)
        filename = sanitize(filename)
        if not filename:
            filename = 'Unknown'

        strm_path = os.path.join(folder, f"{filename}.strm")
        log_to_kodi(f"Attempting to create STRM file: {strm_path}")

        if not os.path.exists(strm_path):
            try:
                async with file_sem:
                    async with aiofiles.open(strm_path, 'w') as f:
                        await f.write(entry['url'])
                    log_to_kodi(f"Created sports STRM: {strm_path}")
            except Exception as e:
                log_to_kodi(f"Failed to write sports STRM file at {strm_path}: {e}")
        else:
            log_to_kodi(f"Sports STRM already exists, skipping: {strm_path}")

async def update_library():
    """Triggers a Kodi video library update."""
    xbmc.executebuiltin('UpdateLibrary(video)')

async def close_async_resources():
    """Closes aiohttp session and cancels remaining tasks."""
    global AIOHTTP_SESSION
    if AIOHTTP_SESSION:
        await AIOHTTP_SESSION.close()
        AIOHTTP_SESSION = None
        log_to_kodi("Aiohttp session closed.")
    # Cancel all running tasks except the current one
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    # Wait for all cancelled tasks to finish
    await asyncio.gather(*tasks, return_exceptions=True) # return_exceptions to prevent stopping on first error
    log_to_kodi("Cancelled remaining asyncio tasks.")

def cleanup_resources_sync():
    """Synchronous cleanup for requests_cache and other resources."""
    try:
        session.close()
        log_to_kodi("Requests cache session closed.")
    except Exception as e:
        log_to_kodi(f"Error closing requests cache session: {e}")

# Register synchronous cleanup with atexit
import atexit
atexit.register(cleanup_resources_sync)

def cleanup_library_folders():
    """
    Remove misplaced .strm files:
    - No movies in TV Shows or Sports
    - No sports in Movies or TV Shows
    - No TV Shows in Sports or Movies
    """
    def is_sport_strm(path):
        # Check if the file is within the SPORT_DIR and potentially matches a sport filename pattern
        # This is a heuristic; a more robust check would involve comparing against a list of known sport titles
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(SPORT_DIR)]) == os.path.abspath(SPORT_DIR)

    def is_tv_strm(path):
        # Check if the file is within the TVSHOWS_DIR and matches typical TV episode/show patterns
        rel_path = os.path.relpath(path, TVSHOWS_DIR)
        return (
            not rel_path.startswith('..') and # Ensure it's actually within TVSHOWS_DIR
            (re.search(r'S\d{2}E\d{2}\.strm$', path, re.IGNORECASE) or # SXXEXX pattern
             re.search(r'Season\s+\d{2}', os.path.dirname(path), re.IGNORECASE)) # In a "Season XX" folder
        )

    def is_movie_strm(path):
        # Check if the file is within the MOVIES_DIR and is directly in it (no subfolders)
        rel_path = os.path.relpath(path, MOVIES_DIR)
        return not rel_path.startswith('..') and os.path.dirname(rel_path) == ''


    # Clean Movies dir
    for fname in os.listdir(MOVIES_DIR):
        if fname.lower().endswith('.strm'):
            fpath = os.path.join(MOVIES_DIR, fname)
            if is_tv_strm(fpath) or is_sport_strm(fpath):
                try:
                    os.remove(fpath)
                    log_to_kodi(f"Removed misplaced STRM from Movies: {fpath}")
                except Exception as e:
                    log_to_kodi(f"Failed to remove {fpath}: {e}")

    # Clean TV Shows dir
    for root, dirs, files in os.walk(TVSHOWS_DIR):
        for fname in files:
            if fname.lower().endswith('.strm'):
                fpath = os.path.join(root, fname)
                if is_movie_strm(fpath) or is_sport_strm(fpath):
                    try:
                        os.remove(fpath)
                        log_to_kodi(f"Removed misplaced STRM from TV Shows: {fpath}")
                    except Exception as e:
                        log_to_kodi(f"Failed to remove {fpath}: {e}")

    # Clean Sports dir
    for root, dirs, files in os.walk(SPORT_DIR):
        for fname in files:
            if fname.lower().endswith('.strm'):
                fpath = os.path.join(root, fname)
                if is_movie_strm(fpath) or is_tv_strm(fpath):
                    try:
                        os.remove(fpath)
                        log_to_kodi(f"Removed misplaced STRM from Sports: {fpath}")
                    except Exception as e:
                        log_to_kodi(f"Failed to remove {fpath}: {e}")


async def main_async():
    """Main asynchronous function to orchestrate the M3U to STRM conversion process."""
    global AIOHTTP_SESSION, ASYNC_LOOP
    # Initialize aiohttp session here
    connector = aiohttp.TCPConnector(limit=TCP_LIMIT)
    AIOHTTP_SESSION = aiohttp.ClientSession(connector=connector)
    sem = Semaphore(SEM_LIMIT)
    file_sem = Semaphore(FILE_SEM_LIMIT)

    try:
        start_time = time.time()
        xbmcgui.Dialog().notification('m3utostrm', 'Script started', xbmcgui.NOTIFICATION_INFO)
        log_to_kodi("=== m3utostrm script started ===")

        series_data, vod_data = load_json_data()
        if not series_data and not vod_data:
            log_to_kodi("Failed to load or fetch Series and VOD data. Aborting.")
            xbmcgui.Dialog().notification('Error', 'Failed to load Series and VOD data', xbmcgui.NOTIFICATION_ERROR)
            return

        xbmcgui.Dialog().notification('m3utostrm', 'Loading and parsing M3U playlist...', xbmcgui.NOTIFICATION_INFO)
        entries = await fetch_m3u()

        # Separate entries by type
        sports_entries = [e for e in entries if e.get('type') == 'sport']
        movies_and_tvs_entries = [e for e in entries if e.get('type') in ('movie', 'tv')]

        # Process sports entries first (no metadata fetching for these)
        await process_sports_entries(sports_entries, SPORT_DIR, file_sem)
        xbmcgui.Dialog().notification('m3utostrm', f'Processed {len(sports_entries)} sports entries.', xbmcgui.NOTIFICATION_INFO)

        # Filter movies and TV shows
        xbmcgui.Dialog().notification('m3utostrm', 'Filtering movie and TV entries by JSON data...', xbmcgui.NOTIFICATION_INFO)
        filtered_movies_and_tvs = filter_entries_by_json(movies_and_tvs_entries, series_data, vod_data)
        xbmcgui.Dialog().notification('m3utostrm', 'Filtering out existing movie and TV files...', xbmcgui.NOTIFICATION_INFO)
        filtered_movies_and_tvs = filter_entries_that_exist(filtered_movies_and_tvs, MOVIES_DIR, TVSHOWS_DIR)

        log_to_kodi(f"After filtering with JSON data & file existence, {len(filtered_movies_and_tvs)} movie and TV entries will be processed.")

        if not filtered_movies_and_tvs and not sports_entries:
            log_to_kodi("No new valid entries found to add.")
            xbmcgui.Dialog().notification('M3U Info', 'No new entries found to add.', xbmcgui.NOTIFICATION_INFO)
            return

        movies = [e for e in filtered_movies_and_tvs if e['type'] == 'movie']
        tvs = [e for e in filtered_movies_and_tvs if e['type'] == 'tv']

        log_to_kodi(f"Found {len(movies)} movies and {len(tvs)} TV shows to process")
        xbmcgui.Dialog().notification('m3utostrm', f'Processing {len(movies)} movies and {len(tvs)} TV shows...', xbmcgui.NOTIFICATION_INFO)

        added_files = 0
        # Track added files before and after
        before_movie_files = set(get_existing_movie_filenames(MOVIES_DIR))
        before_tv_files = set(get_existing_tv_filenames(TVSHOWS_DIR))
        before_sport_files = set(get_existing_sport_filenames(SPORT_DIR))

        # Process movies in batches
        for batch in [movies[i:i+CHUNK_SIZE] for i in range(0, len(movies), CHUNK_SIZE)]:
            await process_batch(batch, MOVIES_DIR, AIOHTTP_SESSION, sem, file_sem)
        # Process TV shows in batches
        for batch in [tvs[i:i+CHUNK_SIZE] for i in range(0, len(tvs), CHUNK_SIZE)]:
            await process_batch(batch, TVSHOWS_DIR, AIOHTTP_SESSION, sem, file_sem)

        await update_library()

        # Count added files
        after_movie_files = set(get_existing_movie_filenames(MOVIES_DIR))
        after_tv_files = set(get_existing_tv_filenames(TVSHOWS_DIR))
        after_sport_files = set(get_existing_sport_filenames(SPORT_DIR))

        added_movies = len(after_movie_files - before_movie_files)
        added_tvs = len(after_tv_files - before_tv_files)
        added_sports = len(after_sport_files - before_sport_files) # Count newly added sports files

        total_added_files = added_movies + added_tvs + added_sports
        log_to_kodi("Library update triggered.")

        end_time = time.time()
        runtime = end_time - start_time

        xbmcgui.Dialog().notification(
            'm3utostrm',
            f'Added {added_movies} movies, {added_tvs} TV shows, {added_sports} sports entries. See log for details.',
            xbmcgui.NOTIFICATION_INFO
        )
        log_to_kodi(f"Summary: Added {added_movies} new movies, {added_tvs} new TV shows, {added_sports} new sports entries.")
        log_to_kodi(f"Total new files added: {total_added_files}")
        log_to_kodi(f"Total runtime: {runtime:.2f} seconds")

        # Call cleanup_library_folders after all processing is complete
        cleanup_library_folders()
        log_to_kodi("Cleanup of library folders complete.")

    except Exception as e:
        log_to_kodi(f"Fatal error during main execution: {e}")
        xbmcgui.Dialog().notification('Error', f'Script encountered a fatal error: {e}', xbmcgui.NOTIFICATION_ERROR)
    finally:
        await close_async_resources()


if __name__ == '__main__':
    try:
        asyncio.run(main_async())
    except Exception as e:
        log_to_kodi(f"Unhandled exception in main: {e}")
        # Ensure synchronous cleanup is still called if async.run fails early
        cleanup_resources_sync()
        sys.exit(1)

