
import os
import requests
from datetime import datetime, timedelta
import re
import logging
import time
import sys
import xbmcvfs
import xbmcaddon
import xbmcgui
import xbmc
import json
import threading
import schedule
import asyncio
import aiohttp
import aiofiles
from functools import partial
import unicodedata

# Initialize Kodi addon
addon = xbmcaddon.Addon()

# Retrieve settings from settings.xml
WORKING_DIR = addon.getSetting("working_dir")
MOVIES_DIR = addon.getSetting("movies_dir")
TV_SHOWS_DIR = addon.getSetting("tv_shows_dir")
SERVER = addon.getSetting("server")
USERNAME = addon.getSetting("username")
PASSWORD = addon.getSetting("password")
UPDATE_TIME = addon.getSetting("update_time")  # Format: "HH:MM"
UPDATE_INTERVAL = int(addon.getSetting("update_interval"))  # Days interval

# Ensure the server URL starts with "http://"
if not SERVER.startswith("http://"):
    SERVER = f"http://{SERVER}"

# Construct M3U URL
M3U_URL = f"{SERVER}/get.php?username={USERNAME}&password={PASSWORD}&type=m3u_plus&output=ts"

# Construct file paths
M3U_FILE = os.path.join(WORKING_DIR, "playlist.m3u")
LOG_FILE = os.path.join(WORKING_DIR, "m3u_processing.log")

# Add counter class
class Stats:
    def __init__(self):
        self.movies_added = 0
        self.shows_added = set()
        self.episodes_added = 0
        self.movies_deleted = 0
        self.shows_deleted = 0
        self.episodes_deleted = 0

# Add after other constants
LOG_SIZE_LIMIT = 10 * 1024 * 1024  # 10MB in bytes

def check_and_clear_log():
    """Check log file size and clear if over limit"""
    try:
        if xbmcvfs.exists(LOG_FILE):
            log_size = xbmcvfs.Stat(LOG_FILE).st_size()
            if log_size > LOG_SIZE_LIMIT:
                logging.info(f"Log size ({log_size/1024/1024:.2f}MB) exceeds limit. Clearing log.")
                with open(LOG_FILE, 'w') as f:
                    f.write("Log cleared due to size limit\n")
                return True
        return False
    except Exception as e:
        print(f"Error checking log size: {str(e)}")
        return False

# Replace existing logging setup with:
if check_and_clear_log():
    xbmcgui.Dialog().notification("M3U Processing", "Log file cleared due to size limit", xbmcgui.NOTIFICATION_INFO, 5000)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def should_download_file():
    """Check if the M3U file should be downloaded based on its age."""
    if not os.path.exists(M3U_FILE):
        return True
    file_time = datetime.fromtimestamp(xbmcvfs.Stat(M3U_FILE).st_mtime())
    return datetime.now() - file_time > timedelta(hours=24)

async def curl_request(url, binary=False):
    """
    Make an async request with custom headers
    binary: If True, return raw bytes instead of text (for images)
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.read() if binary else await response.text()
                return None

    except Exception as e:
        logging.error(f"RequestException: {e}")
        return None

async def download_m3u():
    """Download the M3U file if it is outdated."""
    if should_download_file():
        xbmcgui.Dialog().notification("M3U Processing", "Downloading M3U file...", xbmcgui.NOTIFICATION_INFO, 5000)
        response = await curl_request(M3U_URL, binary=True)
        if response:
            async with aiofiles.open(M3U_FILE, 'wb') as file:
                await file.write(response)
            xbmcgui.Dialog().notification("M3U Processing", "Download complete", xbmcgui.NOTIFICATION_INFO, 5000)
        else:
            xbmcgui.Dialog().notification("M3U Processing", "Failed to download M3U file", xbmcgui.NOTIFICATION_ERROR, 5000)
            sys.exit(1)
    else:
        xbmcgui.Dialog().notification("M3U Processing", "Using existing M3U file (less than 24 hours old)", xbmcgui.NOTIFICATION_INFO, 5000)

def extract_info(extinf_line):
    """
    Extract information about the TV show or movie from the #EXTINF line.
    """
    # Extract show name from tvg-name
    name_match = re.search(r'tvg-name="([^"]+)"', extinf_line)
    tv_show_name = None
    if name_match:
        full_name = name_match.group(1)
        # Remove any leading language codes like "EN - "
        if " - " in full_name:
            full_name = full_name.split(" - ", 1)[1]
        
        # Extract everything up to the year if present
        year_match = re.search(r'(.+?)(?:\s*\(\d{4}\))', full_name)
        if year_match:
            tv_show_name = year_match.group(1).strip()
        else:
            tv_show_name = full_name.strip()

    # Fallback: Extract name from the full line if tvg-name is not found
    if not tv_show_name:
        # Try to extract any text between quotes
        alt_name_match = re.search(r'"([^"]+)"', extinf_line)
        if alt_name_match:
            tv_show_name = alt_name_match.group(1).strip()
        else:
            # Last resort: Use "Unknown Title" with timestamp
            tv_show_name = f"Unknown Title {int(time.time())}"

    # Extract year with fallback
    year_match = re.search(r'\((\d{4})\)', extinf_line)
    tv_show_year = year_match.group(1) if year_match else "0000"

    # Extract season and episode numbers
    season_match = re.search(r'S(\d{2})', extinf_line)
    tv_show_season = season_match.group(1) if season_match else "01"

    episode_match = re.search(r'E(\d{2})', extinf_line)
    tv_show_episode = episode_match.group(1) if episode_match else "01"

    # Log extracted info for debugging
    logging.debug(f"Extracted info: name={tv_show_name}, year={tv_show_year}, season={tv_show_season}, episode={tv_show_episode}")

    return {
        'name': tv_show_name,
        'year': tv_show_year,
        'season': tv_show_season,
        'episode': tv_show_episode
    }

async def create_strm(path, url, stats, create_dirs=True):
    try:
        # Ensure parent directory path is ASCII-safe
        parent_dir = os.path.dirname(path)
        if create_dirs and parent_dir:
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except Exception as e:
                logging.error(f"Error creating directory {parent_dir}: {str(e)}")
                return False
        
        # Ensure file path is ASCII-safe
        safe_path = os.path.join(
            os.path.dirname(path),
            sanitize_filename(os.path.basename(path))
        )
        
        if not os.path.exists(safe_path):
            try:
                # Open in binary mode to avoid encoding issues
                async with aiofiles.open(safe_path, 'wb') as file:
                    await file.write(url.encode('utf-8'))
                return True
            except Exception as e:
                logging.error(f"Error writing to file {safe_path}: {str(e)}")
                return False
        return False
    except Exception as e:
        logging.error(f"Error in create_strm for {path}: {str(e)}")
        return False

def update_progress(current, total, movies, episodes):
    progress = (current / total) * 100
    xbmcgui.Dialog().notification(
        "M3U Processing",
        f"Progress: {progress:.1f}% | Movies: {movies} | Episodes: {episodes}",
        xbmcgui.NOTIFICATION_INFO,
        1000
    )
    sys.stdout.flush()

def sanitize_filename(filename):
    # First, normalize unicode characters
    filename = unicodedata.normalize('NFKD', filename)
    # Remove any remaining non-ASCII characters
    filename = ''.join(c for c in filename if ord(c) < 128)
    # Remove leading numeration (e.g. "17. Movie" -> "Movie")
    filename = re.sub(r'^\s*\d+\.\s*', '', filename)
    # Replace invalid characters
    invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for char in invalid_chars:
        filename = filename.replace(char, '-')
    return filename.strip()

def cleanup_stale_files(valid_files, stats):
    dialog = xbmcgui.Dialog()
    
    # Check Movies directory
    movies_to_delete = []
    for filename in os.listdir(MOVIES_DIR):
        if filename.endswith('.strm'):
            filepath = os.path.join(MOVIES_DIR, filename)
            if filepath not in valid_files:
                movies_to_delete.append(filepath)

    if movies_to_delete:
        if dialog.yesno("Delete Movies", f"Found {len(movies_to_delete)} movies to delete. Proceed?"):
            for filepath in movies_to_delete:
                os.remove(filepath)
                stats.movies_deleted += 1

    # Check TVShows directory
    episodes_to_delete = []
    empty_seasons = []
    empty_shows = []

    for show_folder in os.listdir(TV_SHOWS_DIR):
        show_path = os.path.join(TV_SHOWS_DIR, show_folder)
        if os.path.isdir(show_path):
            empty_show = True
            for season_folder in os.listdir(show_path):
                season_path = os.path.join(show_path, season_folder)
                if os.path.isdir(season_path):
                    files_deleted = False
                    for episode in os.listdir(season_path):
                        if episode.endswith('.strm'):
                            episode_path = os.path.join(season_path, episode)
                            if episode_path not in valid_files:
                                episodes_to_delete.append(episode_path)
                                files_deleted = True

                    # Track empty season folders
                    if not os.listdir(season_path):
                        empty_seasons.append(season_path)
                    elif not files_deleted:
                        empty_show = False

            # Track empty show folders
            if empty_show:
                empty_shows.append(show_path)

    if episodes_to_delete:
        if dialog.yesno("Delete Episodes", f"Found {len(episodes_to_delete)} episodes to delete. Proceed?"):
            for episode_path in episodes_to_delete:
                os.remove(episode_path)
                stats.episodes_deleted += 1

            # After deleting episodes, handle empty folders
            if empty_seasons:
                if dialog.yesno("Delete Empty Seasons", f"Found {len(empty_seasons)} empty season folders. Proceed?"):
                    for season_path in empty_seasons:
                        try:
                            os.rmdir(season_path)
                        except Exception:
                            pass

            if empty_shows:
                if dialog.yesno("Delete Empty Shows", f"Found {len(empty_shows)} empty show folders. Proceed?"):
                    for show_path in empty_shows:
                        try:
                            os.rmdir(show_path)
                            stats.shows_deleted += 1
                        except Exception:
                            pass

def get_server_domain():
    """Extract domain from server URL."""
    return SERVER.split('://')[1] if '://' in SERVER else SERVER

async def process_m3u():
    stats = Stats()
    os.makedirs(MOVIES_DIR, exist_ok=True)
    os.makedirs(TV_SHOWS_DIR, exist_ok=True)
    valid_files = set()

    if xbmcvfs.Stat(M3U_FILE).st_size() == 0:
        xbmcgui.Dialog().notification("M3U Processing", "Error: Empty playlist file. Exiting.", xbmcgui.NOTIFICATION_ERROR, 5000)
        sys.exit(1)

    xbmcgui.Dialog().notification("M3U Processing", "Processing M3U file...", xbmcgui.NOTIFICATION_INFO, 5000)
    async with aiofiles.open(M3U_FILE, 'r', encoding='utf-8', errors='replace') as file:
        content = await file.read()
        lines = content.splitlines()

    # Create tasks for processing entries
    tasks = []
    server_domain = get_server_domain()
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('#EXTINF'):
            info = extract_info(line)
            url = lines[i + 1].strip()
            
            if url:
                if url.startswith(f'http://{server_domain}:80/movie/') or url.startswith(f'https://{server_domain}:80/movie/'):
                    safe_name = sanitize_filename(info['name'])
                    # Only append year if year != "0000"
                    movie_filename = f"{safe_name}.strm" if info['year'] == "0000" else f"{safe_name} {info['year']}.strm"
                    strm_path = os.path.join(MOVIES_DIR, movie_filename)
                    valid_files.add(strm_path)
                    # Create STRM file immediately instead of adding to tasks
                    if await create_strm(strm_path, url, stats, create_dirs=False):
                        stats.movies_added += 1
                
                elif url.startswith(f'http://{server_domain}:80/series/') or url.startswith(f'https://{server_domain}:80/series/'):
                    # Extract clean show name (without season/episode info)
                    full_name = info['name']
                    # Remove 'S01 E01' pattern and similar from show name
                    clean_name = re.sub(r'\s+S\d+\s*E\d+.*$', '', full_name)
                    # Extract year if present
                    year_match = re.search(r'\((\d{4})\)', clean_name)
                    year = year_match.group(1) if year_match else ''
                    # Remove year from name if present
                    show_name = re.sub(r'\s*\(\d{4}\).*$', '', clean_name)
                    # Create proper folder structure
                    show_folder = os.path.join(TV_SHOWS_DIR, f"{sanitize_filename(show_name)}{' ' + year if year else ''}")
                    season_folder = os.path.join(show_folder, f"Season {int(info['season'])}")
                    episode_filename = f"{sanitize_filename(show_name)} S{info['season']}E{info['episode']}.strm"
                    strm_path = os.path.join(season_folder, episode_filename)
                    valid_files.add(strm_path)
                    
                    os.makedirs(show_folder, exist_ok=True)
                    os.makedirs(season_folder, exist_ok=True)
                    
                    if not os.path.exists(strm_path):
                        if await create_strm(strm_path, url, stats):
                            stats.shows_added.add(show_name)
                            stats.episodes_added += 1
            i += 2
        else:
            i += 1
        
        # Update progress every 100 items
        if i % 100 == 0:
            update_progress(i, len(lines), stats.movies_added, stats.episodes_added)
    
    # Cleanup stale files after processing
    cleanup_stale_files(valid_files, stats)
    xbmcgui.Dialog().notification("M3U Processing", "Processing complete!", xbmcgui.NOTIFICATION_INFO, 5000)
    return stats

async def async_main():
    start_time = time.time()
    xbmcgui.Dialog().notification("M3U Processing", "Starting M3U processing script...", xbmcgui.NOTIFICATION_INFO, 5000)
    logging.info("Script started")
   
    await download_m3u()
    stats = await process_m3u()
   
    end_time = time.time()
    run_time = end_time - start_time
   
    xbmcgui.Dialog().notification(
        "M3U Processing",
        f"Summary:\nRun time: {run_time:.2f}s\nMovies added: {stats.movies_added}\nTV Shows added: {len(stats.shows_added)}\nEpisodes added: {stats.episodes_added}\nMovies deleted: {stats.movies_deleted}\nTV Shows deleted: {stats.shows_deleted}\nEpisodes deleted: {stats.episodes_deleted}",
        xbmcgui.NOTIFICATION_INFO,
        10000
    )
    logging.info(f"Script finished")
    logging.info(f"Total run time: {run_time:.2f} seconds")
    logging.info(f"Movies added: {stats.movies_added}")
    logging.info(f"TV Shows added: {len(stats.shows_added)}")
    logging.info(f"Episodes added: {stats.episodes_added}")
    logging.info(f"Movies deleted: {stats.movies_deleted}")
    logging.info(f"TV Shows deleted: {stats.shows_deleted}")
    logging.info(f"Episodes deleted: {stats.episodes_deleted}")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(async_main())
    finally:
        loop.close()
