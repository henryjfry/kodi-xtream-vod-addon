import sys
import os, os.path
import errno
# Ensure bundled libs take priority
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), 'resources', 'lib'))

# --- Standard library ---
import re
import json

import shutil
import time

from xml.etree.ElementTree import Element, SubElement, tostring
from datetime import datetime

from unidecode import unidecode


import requests
from requests_cache import CachedSession
#from rapidfuzz import fuzz, process

import Utils
from Utils import log_to_kodi as log_to_kodi
from Utils import remove_non_ascii as remove_non_ascii
xbmc_flag = Utils.xbmc_flag


ADDON = Utils.ADDON
SERVER_ADD = Utils.SERVER_ADD
USERNAME = Utils.USERNAME
PASSWORD = Utils.PASSWORD
MOVIES_DIR = Utils.MOVIES_DIR
TVSHOWS_DIR = Utils.TVSHOWS_DIR
SPORT_DIR = Utils.SPORT_DIR
WORKING_DIR = Utils.WORKING_DIR
TMDB_API_KEY = Utils.TMDB_API_KEY
SETTING_XML = Utils.SETTING_XML


if not SERVER_ADD.startswith("http://"):
	SERVER_ADD = f"http://{SERVER_ADD}"

def folder_exists(folder_path):
	if not os.path.exists(folder_path):
		os.makedirs(folder_path, exist_ok=True)
	return


# Updated API URLs - now we'll use the VOD API directly instead of M3U
SERIES_API_URL = f'{SERVER_ADD}/player_api.php?username={USERNAME}&password={PASSWORD}&action=get_series'
VOD_API_URL = f'{SERVER_ADD}/player_api.php?username={USERNAME}&password={PASSWORD}&action=get_vod_streams'
LIVE_API_URL = f'{SERVER_ADD}/player_api.php?username={USERNAME}&password={PASSWORD}&action=get_live_streams'
get_series_categories = f'{SERVER_ADD}/player_api.php?username={USERNAME}&password={PASSWORD}&action=get_series_categories'
get_series_info = f'{SERVER_ADD}/player_api.php?username={USERNAME}&password={PASSWORD}&action=get_series_info'
get_vod_categories = f'{SERVER_ADD}/player_api.php?username={USERNAME}&password={PASSWORD}&action=get_vod_categories'
get_live_categories = f'{SERVER_ADD}/player_api.php?username={USERNAME}&password={PASSWORD}&action=get_live_categories'



# Define paths for JSON cache files
if xbmc_flag:
	CACHE_DIR = os.path.join(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')), 'cache')
else:
	CACHE_DIR = os.path.join(WORKING_DIR, 'cache')
SERIES_JSON_PATH = os.path.join(CACHE_DIR, 'ipvos-all_stream_Series.json')
VOD_JSON_PATH = os.path.join(CACHE_DIR, 'ipvos-all_stream_VOD.json')
LIVE_JSON_PATH = os.path.join(CACHE_DIR, 'ipvos-all_stream_Live.json')
SERIES_INFO_CACHE_PATH = os.path.join(CACHE_DIR, 'series_info_cache.json')

#folder_exists(WORKING_DIR)
#folder_exists(TVSHOWS_DIR)
#folder_exists(MOVIES_DIR)
#folder_exists(CACHE_DIR)

session = CachedSession(cache_name=os.path.join(CACHE_DIR,'xtream_cache'), backend='sqlite', expire_after=(60 * 60 * 24)) ##1 day
#session_tv = CachedSession(cache_name=os.path.join(CACHE_DIR,'xtream_cache_tv'), backend='sqlite', expire_after=(60 * 60 * 24 * 14)) ##14 day

def VOD_json(url, series_id=None, force_refresh=False):
	if series_id:
		url = get_series_info + '&series_id=%s' % str(series_id)
		if force_refresh == True:
			session.cache.delete_url(url)
		response = session.get(url)
	else:
		if force_refresh == True:
			session.cache.delete_url(url)
		response = session.get(url)
	try: status_code = response.status_code
	except: status_code = 400
	if status_code == 200:
		return response.json()
	else:
		return []

def update_LIVE():
	VOD_json(LIVE_API_URL)

def update_VOD():
	VOD_json(VOD_API_URL)
	VOD_json(SERIES_API_URL)

def contains_non_english(text):
	return any(ord(char) > 127 for char in text)



def db_create(conn):
	cursor = conn.cursor()
	cursor.execute('''
	CREATE TABLE IF NOT EXISTS PROCESSED (
		id INT,
		media_type TEXT,
		tmdb_id INT,
		added INT,
		container_ext TEXT,
		title TEXT,
		kodi_added INT,
		strm_path TEXT,
		updated INT,
		UNIQUE(id, title, media_type)
	)
	''')
	conn.commit()
	return

def db_check_exists(id = None, title = None, media_type = None):
	conn = Utils.db_con
	cursor = conn.cursor()
	db_create(conn)
	if media_type == 'TV_SHOW':
		result = cursor.execute('''
		SELECT * FROM PROCESSED WHERE ID = %s and media_type = '%s'
		''' % (id, media_type))
		results = result.fetchall()
		if results != []:
			updated = results[0][8]
			if int(title) >= int(updated):
				return True
			else:
				return False
	else:
		result = cursor.execute('''
		SELECT * FROM PROCESSED WHERE ID = %s and title = '%s' and media_type = '%s'
		''' % (id, title, media_type))
		return result.fetchall()

"""
def db_update(data):
	conn = Utils.db_con
	cursor = conn.cursor()
	#cursor.execute('DROP TABLE PROCESSED')
	db_create(conn)
	cursor.execute('''
	INSERT OR IGNORE INTO PROCESSED (id, media_type, tmdb_id, added, container_ext, title, kodi_added, strm_path, updated)
	VALUES (:id, :media_type, :tmdb_id, :added, :container_ext, :title, :kodi_added, :strm_path, :updated)
	''', data)
	conn.commit()
"""

def db_update(data):
	conn = Utils.db_con
	cursor = conn.cursor()
	db_create(conn)

	cursor.execute('''
	INSERT INTO PROCESSED (id, media_type, tmdb_id, added, container_ext, title, kodi_added, strm_path, updated)
	VALUES (:id, :media_type, :tmdb_id, :added, :container_ext, :title, :kodi_added, :strm_path, :updated)
	ON CONFLICT(id, title, media_type) DO UPDATE SET
		media_type = excluded.media_type,
		tmdb_id = excluded.tmdb_id,
		added = excluded.added,
		container_ext = excluded.container_ext,
		title = excluded.title,
		kodi_added = excluded.kodi_added,
		strm_path = excluded.strm_path,
		updated = excluded.updated
	''', data)

	conn.commit()

def db_remove_missing_on_json(id_added_list):
	#valid_pairs = [(entry['stream_id'], entry['added']) for entry in valid_entries]
	valid_pairs = id_added_list

	# Connect to DB
	conn = Utils.db_con
	cursor = conn.cursor()

	# Create a temporary table to hold valid pairs
	cursor.execute('DROP TABLE IF EXISTS temp_valid')
	cursor.execute('''
	CREATE TEMP TABLE temp_valid (
		stream_id TEXT,
		added TEXT,
		media_type TEXT
	)
	''')

	# Insert valid pairs into temp table
	cursor.executemany('INSERT INTO temp_valid (stream_id, added, media_type) VALUES (:stream_id, :added, :media_type)', valid_pairs)

	# Delete rows from PROCESSED that are not in temp_valid
	cursor.execute('''
	DELETE FROM PROCESSED
	WHERE NOT EXISTS (
		SELECT 1 FROM temp_valid
		WHERE temp_valid.stream_id = PROCESSED.id
		AND temp_valid.added = PROCESSED.added
		AND temp_valid.media_type = PROCESSED.media_type
	)
	''')

	# Commit and close
	conn.commit()
	conn.close()

	

# Taken from https://stackoverflow.com/a/600612/119527
def mkdir_p(path):
	try:
		os.makedirs(path)
	except OSError as exc: # Python >2.5
		if exc.errno == errno.EEXIST and os.path.isdir(path):
			pass
		else: raise

def safe_open_w(path):
	''' Open "path" for writing, creating any parent directories as needed.
	'''
	mkdir_p(os.path.dirname(path))
	return open(path, 'w', encoding="utf-8")


def kodi_movie_nfo(meta):
	meta = remove_non_ascii(meta)
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
	SubElement(rating_trakt, 'value').text = ''
	SubElement(rating_trakt, 'votes').text = ''

	SubElement(root, 'userrating').text = str(meta.get('vote_average', ''))
	SubElement(root, 'top250').text = '0'
	SubElement(root, 'outline').text = ''
	SubElement(root, 'plot').text = meta.get('overview', '')
	SubElement(root, 'tagline').text = meta.get('tagline', '')
	SubElement(root, 'runtime').text = str(meta.get('runtime', ''))

	poster_path = meta.get('poster_path')
	backdrop_path = meta.get('backdrop_path')
	if poster_path:
		SubElement(root, 'thumb', aspect='poster', preview=f"https://image.tmdb.org/t/p/original{poster_path}").text = f"https://image.tmdb.org/t/p/original{poster_path}"
	if backdrop_path:
		SubElement(root, 'thumb', aspect='landscape', preview=f"https://image.tmdb.org/t/p/original{backdrop_path}").text = f"https://image.tmdb.org/t/p/original{backdrop_path}"
		fanart = SubElement(root, 'fanart')
		SubElement(fanart, 'thumb', preview=f"https://image.tmdb.org/t/p/w780{backdrop_path}").text = f"https://image.tmdb.org/t/p/original{backdrop_path}"

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

	for g in meta.get('genres', []):
		SubElement(root, 'genre').text = g.get('name', '')
	for c in meta.get('production_countries', []):
		SubElement(root, 'country').text = c.get('name', '')

	if meta.get('belongs_to_collection'):
		set_el = SubElement(root, 'set')
		SubElement(set_el, 'name').text = meta['belongs_to_collection'].get('name', '')
		SubElement(set_el, 'overview').text = ''

	for w in meta.get('credits', {}).get('crew', []):
		if w.get('job', '').lower() == 'writer':
			SubElement(root, 'credits').text = w.get('name', '')
	for d in meta.get('credits', {}).get('crew', []):
		if d.get('job', '').lower() == 'director':
			SubElement(root, 'director').text = d.get('name', '')

	SubElement(root, 'premiered').text = meta.get('release_date', '')
	SubElement(root, 'year').text = (meta.get('release_date') or '')[:4]
	SubElement(root, 'status').text = ''
	SubElement(root, 'code').text = ''
	SubElement(root, 'aired').text = ''

	for s in meta.get('production_companies', []):
		SubElement(root, 'studio').text = s.get('name', '')
	SubElement(root, 'trailer').text = ''

	for idx, actor in enumerate(meta.get('credits', {}).get('cast', [])):
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

def kodi_tvshow_nfo(meta):
	meta = remove_non_ascii(meta)
	root = Element('tvshow')
	SubElement(root, 'title').text = meta.get('name', '')
	SubElement(root, 'originaltitle').text = meta.get('original_name', meta.get('name', ''))
	SubElement(root, 'showtitle').text = meta.get('name', '')

	ratings = SubElement(root, 'ratings')
	imdb_id = meta.get('external_ids', {}).get('imdb_id')
	tvdb_id = meta.get('external_ids', {}).get('tvdb_id')
	tmdb_id = meta.get('id')

	rating_imdb = SubElement(ratings, 'rating', name='imdb', max='10', default='true')
	SubElement(rating_imdb, 'value').text = ''
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
	SubElement(root, 'displayseason').text = '-1'
	SubElement(root, 'displayepisode').text = '-1'
	SubElement(root, 'outline').text = ''
	SubElement(root, 'plot').text = meta.get('overview', '')
	SubElement(root, 'tagline').text = meta.get('tagline', '')
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
		SubElement(root, 'thumb', aspect='landscape', preview=f"https://image.tmdb.org/t/p/w780{backdrop_path}").text = f"https://image.tmdb.org/t/p/original{backdrop_path}"
	if logo_path:
		SubElement(root, 'thumb', aspect='logos', preview=f"https://image.tmdb.org/t/p/w780{logo_path}").text = f"https://image.tmdb.org/t/p/original{logo_path}"
	if poster_path:
		SubElement(root, 'thumb', aspect='poster', preview=f"https://image.tmdb.org/t/p/w780{poster_path}").text = f"https://image.tmdb.org/t/p/original{poster_path}"

	for season_data in meta.get('seasons', []):
		s_poster = season_data.get('poster_path')
		s_num = season_data.get('season_number')
		if s_poster and s_num is not None:
			SubElement(root, 'thumb', season=str(s_num), type='season', aspect='poster', preview=f"https://image.tmdb.org/t/p/w780{s_poster}").text = f"https://image.tmdb.org/t/p/original{s_poster}"

	fanart = SubElement(root, 'fanart')
	fanart_paths = []
	if meta.get('images'):
		fanart_paths = [img['file_path'] for img in meta['images'].get('backdrops', [])[:2] if img.get('file_path')]
	elif backdrop_path:
		fanart_paths = [backdrop_path]
	for fpath in fanart_paths:
		SubElement(fanart, 'thumb', preview=f"https://image.tmdb.org/t/p/original{fpath}").text = f"https://image.tmdb.org/t/p/original{fpath}"

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

	for g in meta.get('genres', []):
		SubElement(root, 'genre').text = g.get('name', '')

	premiered = meta.get('first_air_date', '')
	SubElement(root, 'premiered').text = premiered
	SubElement(root, 'year').text = premiered[:4] if premiered else ''
	SubElement(root, 'status').text = meta.get('status', '')
	SubElement(root, 'code').text = ''
	SubElement(root, 'aired').text = ''

	for s in meta.get('networks', []):
		SubElement(root, 'studio').text = s.get('name', '')
	SubElement(root, 'trailer').text = ''

	for idx, actor in enumerate(meta.get('credits', {}).get('cast', [])):
		actor_el = SubElement(root, 'actor')
		SubElement(actor_el, 'name').text = actor.get('name', '')
		SubElement(actor_el, 'role').text = actor.get('character', '')
		SubElement(actor_el, 'order').text = str(idx)
		if actor.get('profile_path'):
			SubElement(actor_el, 'thumb').text = f"https://image.tmdb.org/t/p/original{actor['profile_path']}"

	for season_data in meta.get('seasons', []):
		if season_data.get('season_number') is not None and season_data.get('name'):
			namedseason = SubElement(root, 'namedseason')
			namedseason.set('number', str(season_data['season_number']))
			namedseason.text = season_data['name']

	resume = SubElement(root, 'resume')
	SubElement(resume, 'position').text = '0.000000'
	SubElement(resume, 'total').text = '0.000000'
	SubElement(root, 'dateadded').text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

	return '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n' + tostring(root, encoding='utf-8').decode()


def kodi_season_nfo(season, tvshow):
	from xml.etree.ElementTree import Element, SubElement, tostring
	from datetime import datetime

	def remove_non_ascii(data):
		if isinstance(data, dict):
			return {k: remove_non_ascii(v) for k, v in data.items()}
		elif isinstance(data, list):
			return [remove_non_ascii(item) for item in data]
		elif isinstance(data, str):
			return ''.join(c for c in data if ord(c) < 128)
		return data

	season = remove_non_ascii(season)
	tvshow = remove_non_ascii(tvshow)

	root = Element('season')
	SubElement(root, 'title').text = f"{tvshow.get('name', '')} - {season.get('name', '')}"
	SubElement(root, 'plot').text = season.get('overview', '')
	SubElement(root, 'season').text = str(season.get('season_number', ''))
	SubElement(root, 'year').text = (season.get('air_date') or '')[:4]
	SubElement(root, 'id').text = str(season.get('id', ''))
	SubElement(root, 'tvshowid').text = str(tvshow.get('id', ''))

	# Poster thumbnail
	poster_path = season.get('poster_path')
	if poster_path:
		SubElement(root, 'thumb', aspect='poster', preview=f"https://image.tmdb.org/t/p/w780{poster_path}").text = f"https://image.tmdb.org/t/p/original{poster_path}"

	# Fanart from TV show
	fanart = SubElement(root, 'fanart')
	backdrops = tvshow.get('images', {}).get('backdrops', [])
	for backdrop in backdrops[:2]:
		path = backdrop.get('file_path')
		if path:
			SubElement(fanart, 'thumb', preview=f"https://image.tmdb.org/t/p/original{path}").text = f"https://image.tmdb.org/t/p/original{path}"

	# Ratings
	ratings = SubElement(root, 'ratings')
	rating_tmdb = SubElement(ratings, 'rating', name='tmdb', max='10', default='true')
	SubElement(rating_tmdb, 'value').text = str(tvshow.get('vote_average', ''))
	SubElement(rating_tmdb, 'votes').text = str(tvshow.get('vote_count', ''))

	# Genres
	for genre in tvshow.get('genres', []):
		SubElement(root, 'genre').text = genre.get('name', '')

	# Studios (networks)
	for network in tvshow.get('networks', []):
		SubElement(root, 'studio').text = network.get('name', '')

	# Named season
	if season.get('season_number') is not None and season.get('name'):
		namedseason = SubElement(root, 'namedseason')
		namedseason.set('number', str(season.get('season_number')))
		namedseason.text = season.get('name')

	# Resume block
	resume = SubElement(root, 'resume')
	SubElement(resume, 'position').text = '0.000000'
	SubElement(resume, 'total').text = '0.000000'

	# Date added
	SubElement(root, 'dateadded').text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

	return '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n' + tostring(root, encoding='utf-8').decode()


def kodi_episode_nfo(episode, tvshow):
	episode = remove_non_ascii(episode)
	tvshow = remove_non_ascii(tvshow)

	root = Element('episodedetails')
	SubElement(root, 'title').text = episode.get('name', '')
	SubElement(root, 'showtitle').text = tvshow.get('name', '')
	SubElement(root, 'season').text = str(episode.get('season_number', ''))
	SubElement(root, 'episode').text = str(episode.get('episode_number', ''))
	SubElement(root, 'displayseason').text = '-1'
	SubElement(root, 'displayepisode').text = '-1'
	SubElement(root, 'aired').text = episode.get('air_date', '')
	SubElement(root, 'plot').text = episode.get('overview', '')
	SubElement(root, 'tagline').text = ''
	SubElement(root, 'runtime').text = str(episode.get('runtime', ''))
	SubElement(root, 'mpaa').text = ''
	SubElement(root, 'playcount').text = '0'
	SubElement(root, 'lastplayed').text = ''
	SubElement(root, 'id').text = str(episode.get('id', ''))

	imdb_id = episode.get('external_ids', {}).get('imdb_id')
	tmdb_id = episode.get('id')
	tvdb_id = episode.get('external_ids', {}).get('tvdb_id')
	if imdb_id:
		SubElement(root, 'uniqueid', type='imdb').text = imdb_id
	if tmdb_id:
		SubElement(root, 'uniqueid', type='tmdb', default='true').text = str(tmdb_id)
	if tvdb_id:
		SubElement(root, 'uniqueid', type='tvdb').text = str(tvdb_id)

	ratings = SubElement(root, 'ratings')
	rating_imdb = SubElement(ratings, 'rating', name='imdb', max='10', default='true')
	SubElement(rating_imdb, 'value').text = str(episode.get('vote_average', ''))
	SubElement(rating_imdb, 'votes').text = str(episode.get('vote_count', ''))
	rating_tmdb = SubElement(ratings, 'rating', name='tmdb', max='10')
	SubElement(rating_tmdb, 'value').text = str(episode.get('vote_average', ''))
	SubElement(rating_tmdb, 'votes').text = str(episode.get('vote_count', ''))
	rating_trakt = SubElement(ratings, 'rating', name='trakt', max='10')
	SubElement(rating_trakt, 'value').text = ''
	SubElement(rating_trakt, 'votes').text = ''
	SubElement(root, 'userrating').text = '0'
	SubElement(root, 'top250').text = '0'

	for g in tvshow.get('genres', []):
		SubElement(root, 'genre').text = g.get('name', '')

	for w in episode.get('crew', []):
		if w.get('job', '').lower() == 'writer':
			SubElement(root, 'credits').text = w.get('name', '')
	for d in episode.get('crew', []):
		if d.get('job', '').lower() == 'director':
			SubElement(root, 'director').text = d.get('name', '')

	for s in tvshow.get('networks', []):
		SubElement(root, 'studio').text = s.get('name', '')
	SubElement(root, 'trailer').text = ''

	thumbs = []
	if episode.get('still_path'):
		thumbs.append(episode['still_path'])
	if episode.get('images'):
		thumbs += [img['file_path'] for img in episode['images'].get('stills', []) if img.get('file_path')]
	for t in thumbs[:2]:
		SubElement(root, 'thumb', aspect='thumb', preview=f"https://image.tmdb.org/t/p/w780{t}").text = f"https://image.tmdb.org/t/p/original{t}"

	resume = SubElement(root, 'resume')
	SubElement(resume, 'position').text = '0.000000'
	SubElement(resume, 'total').text = '0.000000'
	SubElement(root, 'dateadded').text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

	cast = episode.get('guest_stars', []) or episode.get('credits', {}).get('cast', [])
	for idx, actor in enumerate(cast):
		actor_el = SubElement(root, 'actor')
		SubElement(actor_el, 'name').text = actor.get('name', '')
		SubElement(actor_el, 'role').text = actor.get('character', '')
		SubElement(actor_el, 'order').text = str(idx)
		if actor.get('profile_path'):
			SubElement(actor_el, 'thumb').text = f"https://image.tmdb.org/t/p/original{actor['profile_path']}"

	return '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n' + tostring(root, encoding='utf-8').decode()


def startup_update():
	update_LIVE()
	update_VOD()
	vod_TV = VOD_json(SERIES_API_URL)

def get_series_id(series_id_item):
	series_id = series_id_item['series_id']
	return series_id

def check_db_missing_on_json():
	#remove entries from the DB which are no longer present in the VOD json data
	id_added_list = []
	vod_TV = VOD_json(SERIES_API_URL)
	for ix, i in enumerate(vod_TV):
		print(i['name'], ix,' of total shows ' , len(vod_TV))
		series_id=get_series_id(i)
		vod_series = VOD_json(get_series_info, series_id=series_id)
		if len(vod_series['seasons']) == 0:
			seasons = 'episodes'
		else:
			seasons = 'seasons'

		try: test = vod_series[seasons]
		except: continue
		
		for j in vod_series[seasons]:
			if type(j) == type(''):
				curr_season = j
			elif type(j) == type({}):
				curr_season = str(j['season_number'])
			elif type(j) == type([]):
				for jx in j:
					curr_item = {"stream_id": jx['id'], "added": jx['added'], 'media_type': 'TV'}
					id_added_list.append(curr_item)
					#print(2,curr_item )
					continue

			if not vod_series or 'seasons' not in vod_series or 'episodes' not in vod_series:
				continue
			if curr_season not in vod_series['episodes']:
				continue
			for jx in vod_series['episodes'][curr_season]:
				curr_item = {"stream_id": jx['id'], "added": jx['added'], 'media_type': 'TV'}
				#print(1,curr_item )


	vod_json = VOD_json(VOD_API_URL)
	for i in vod_json:
		curr_item = {"stream_id": i['stream_id'], "added": i['added'], 'media_type': 'MOVIE'}
		id_added_list.append(curr_item)
		#print(1,curr_item )

	db_remove_missing_on_json(id_added_list)


def check_db_missing_on_json2():
	#remove entries from the DB which are no longer present in the VOD json data
	id_added_list = []
	vod_TV = VOD_json(SERIES_API_URL)
	for ix, i in enumerate(vod_TV):
		#print(i['name'], ix,' of total shows ' , len(vod_TV))
		series_id = get_series_id(i)
		vod_series = VOD_json(get_series_info, series_id=series_id)
		#log_to_kodi(i['name'])
		if not vod_series or 'seasons' not in vod_series or 'episodes' not in vod_series:
			continue

		seasons = 'episodes'
		episodes_type = 'string'
		for ib in vod_series['seasons']:
			if 'season_number' in str(ib):
				seasons = 'seasons'
		if seasons == 'episodes':
			for ic in vod_series['episodes']:
				if type(ic) == type(''):
					episodes_type = 'string'
				elif type(ic) == type([]):
					episodes_type = 'list'

		def do_episode(id_added_list, ep_item, tv_item, season_item):
			jx = ep_item
			i = tv_item
			j = season_item
			if type(season_item) == type(''):
				j = {'season_number': int(season_item)}
			if j.get('season_number','') == '':
				j['season_number'] = j['season']
			if j['season_number'] == 0 or jx['episode_num'] == 0:
				return id_added_list, False

			curr_item = {"stream_id": jx['id'], "added": jx['added'], 'media_type': 'TV'}
			id_added_list.append(curr_item)
			print(curr_item)
			return id_added_list, True

		if type(vod_series.get('episodes',{})) == type([]):
			if type(vod_series.get('episodes',{})[0]) == type([]):
				seasons = 'episodes'
				episodes_type = 'list'

		if episodes_type == 'string':
			for j in vod_series[seasons]:
				try: test = vod_series[seasons][curr_season]
				except: seasons = 'episodes'
				if type(j) == type({}):
					curr_season = str(j['season_number'])
				else:
					curr_season = str(j)
				if vod_series.get(seasons,{}).get(curr_season,'') == '':
					continue
				for jx in vod_series[seasons][curr_season]:
					try: var_test = i.get('tmdb',False)
					except: var_test = False
					if var_test:
						id_added_list,episode_result = do_episode(id_added_list=id_added_list,ep_item=jx, tv_item=i, season_item=j)
					else:
						id_added_list,episode_result = do_episode(id_added_list=id_added_list,ep_item=jx, tv_item=vod_series['info'], season_item=j)
					if episode_result == False:
						continue
			print(i['name'], ix,' of total shows ' , len(vod_TV))
		else:
			for j in vod_series[seasons]:
				if i.get('tmdb','') != '':
					tv_item = i
				else:
					tv_item = vod_series['info']
				for jx in j:
					if type(j) == type([]):
						id_added_list,episode_result = do_episode(id_added_list=id_added_list,ep_item=jx, tv_item=tv_item, season_item=j[0])
					else:
						id_added_list,episode_result = do_episode(id_added_list=id_added_list,ep_item=jx, tv_item=tv_item, season_item=j)
					if episode_result == False:
						continue
			print(i['name'], ix,' of total shows ' , len(vod_TV))

	vod_json = VOD_json(VOD_API_URL)
	for i in vod_json:
		curr_item = {"stream_id": i['stream_id'], "added": i['added'], 'media_type': 'MOVIE'}
		id_added_list.append(curr_item)
		#print(1,curr_item )

	db_remove_missing_on_json(id_added_list)



def tv_create_strm(vod_TV):
	for ix, i in enumerate(vod_TV):
		series_id = get_series_id(i)

		tv_check_processed = db_check_exists(id = series_id, title = i['last_modified'], media_type='TV_SHOW')
		if tv_check_processed == True:
			continue
		vod_series = VOD_json(get_series_info, series_id=series_id)
		log_to_kodi(i['name'])
		if not vod_series or 'seasons' not in vod_series or 'episodes' not in vod_series:
			continue

		seasons = 'episodes'
		episodes_type = 'string'
		for ib in vod_series['seasons']:
			if 'season_number' in str(ib):
				seasons = 'seasons'
		if seasons == 'episodes':
			for ic in vod_series['episodes']:
				if type(ic) == type(''):
					episodes_type = 'string'
				elif type(ic) == type([]):
					episodes_type = 'list'

		def do_episode(ep_item, tv_item, season_item):
			jx = ep_item
			i = tv_item
			j = season_item
			if type(season_item) == type(''):
				j = {'season_number': int(season_item)}
			if j.get('season_number','') == '':
				j['season_number'] = j['season']

			check_title = jx['title'].replace("'",'')
			if db_check_exists(id = jx['id'], title = check_title, media_type='TV'):
				return False
			
			result_list = []
			cache_dict = {}
			strm_url = f"{SERVER_ADD}/series/{USERNAME}/{PASSWORD}/{jx['id']}.{jx['container_extension']}"
			if j['season_number'] != 0 and jx['episode_num'] != 0:
				episode_info, tvshow = Utils.extended_episode_info(tvshow_id=i['tmdb'], season=j['season_number'], episode=jx['episode_num'], cache_time=7)
			else:
				return False

			try:
				if contains_non_english(tvshow['original_name']):
					original_title = tvshow['name']
				else:
					original_title = tvshow['original_name']
			except:
				try:
					original_title = tvshow['name']
				except:
					return False

			original_title = Utils.make_safe_filename(original_title)
			season_num = str(j['season_number']).zfill(2)
			episode_num = str(jx['episode_num']).zfill(2)

			folder_name = f"{original_title}.[tmdb={i['tmdb']}]/Season.{season_num}"
			show_folder = f"{original_title}.[tmdb={i['tmdb']}]"
			base_filename = f"{original_title}.S{season_num}E{episode_num}.[tmdb={i['tmdb']}]"

			strm_episode_path = os.path.join(TVSHOWS_DIR, folder_name, f"{base_filename}.strm")
			xml_episode_nfo_path = os.path.join(TVSHOWS_DIR, folder_name, f"{base_filename}.nfo")
			nfo_url_path = os.path.join(TVSHOWS_DIR, show_folder, "tvshow.nfo")
			xml_tvshow_nfo_path = os.path.join(TVSHOWS_DIR, show_folder, show_folder + ".nfo")
			xml_season_nfo_path = os.path.join(TVSHOWS_DIR, folder_name, "season.nfo")

			nfo_url = f"https://www.themoviedb.org/tv/{i['tmdb']}"

			with safe_open_w(strm_episode_path) as f:
				f.write(strm_url)

			with safe_open_w(nfo_url_path) as f:
				f.write(nfo_url)

			with safe_open_w(xml_episode_nfo_path) as f:
				xml_episode_nfo = kodi_episode_nfo(episode_info, tvshow)
				f.write(xml_episode_nfo)

			with safe_open_w(xml_tvshow_nfo_path) as f:
				xml_tvshow_nfo = kodi_tvshow_nfo(tvshow)
				f.write(xml_tvshow_nfo)

			with safe_open_w(xml_season_nfo_path) as f:
				xml_season_nfo = kodi_season_nfo(j, tvshow)
				f.write(xml_season_nfo)

			result_list[:] = [*result_list, *[strm_url,nfo_url_path,nfo_url,xml_episode_nfo_path,xml_episode_nfo,xml_tvshow_nfo_path,xml_tvshow_nfo,xml_season_nfo]]
			#result_list.append()

			#log_to_kodi(result_list)
			cache_dict['id'], cache_dict['tmdb_id'], cache_dict['added'], cache_dict['container_ext'],cache_dict['title'], cache_dict['strm_path'] = jx['id'], i['tmdb'], jx['added'], jx['container_extension'],check_title, strm_episode_path
			cache_dict['kodi_added'] = int(time.time())
			cache_dict['media_type'] = 'TV'
			cache_dict['updated'] = i['last_modified']
			
			#log_to_kodi(cache_dict)
			db_update(cache_dict)
			log_to_kodi(f"Created: {strm_episode_path}")
			return True

		if type(vod_series.get('episodes',{})) == type([]):
			if type(vod_series.get('episodes',{})[0]) == type([]):
				seasons = 'episodes'
				episodes_type = 'list'

		if episodes_type == 'string':
			for j in vod_series[seasons]:
				try: test = vod_series[seasons][curr_season]
				except: seasons = 'episodes'
				if type(j) == type({}):
					curr_season = str(j['season_number'])
				else:
					curr_season = str(j)
				if vod_series.get(seasons,{}).get(curr_season,'') == '':
					continue
				for jx in vod_series[seasons][curr_season]:
					try: var_test = i.get('tmdb',False)
					except: var_test = False
					if var_test:
						episode_result = do_episode(ep_item=jx, tv_item=i, season_item=j)
					else:
						episode_result = do_episode(ep_item=jx, tv_item=vod_series['info'], season_item=j)
					if episode_result == False:
						continue
			print(i['name'], ix,' of total shows ' , len(vod_TV))
		else:
			for j in vod_series[seasons]:
				if i.get('tmdb','') != '':
					tv_item = i
				else:
					tv_item = vod_series['info']
				for jx in j:
					if type(j) == type([]):
						episode_result = do_episode(ep_item=jx, tv_item=tv_item, season_item=j[0])
					else:
						episode_result = do_episode(ep_item=jx, tv_item=tv_item, season_item=j)
					if episode_result == False:
						continue
			print(i['name'], ix,' of total shows ' , len(vod_TV))
		cache_dict = {}
		cache_dict['id'], cache_dict['tmdb_id'], cache_dict['added'], cache_dict['container_ext'],cache_dict['title'], cache_dict['strm_path'] = series_id, i['tmdb'], jx['added'], 'EXT_TV_SHOW','TITLE_TV_SHOW', 'STRM_TV_SHOW'
		cache_dict['kodi_added'] = int(time.time())
		cache_dict['media_type'] = 'TV_SHOW'
		cache_dict['updated'] = i['last_modified']
		#db_check_exists(id = series_id, title = i['updated'], media_type='TV_SHOW')
		db_update(cache_dict)



def movie_create_strm(vod_movie):
	vod_json = vod_movie
	for i in vod_json:
		log_to_kodi(i['name'])
		check_title = i['name'].replace("'",'')
		if db_check_exists(id = i['stream_id'], title = check_title, media_type='MOVIE'):
			continue
		if i['stream_type'] == 'movie':
			if i['tmdb'] == '':
				continue
			result_list = []
			cache_dict = {}
			movie_info = Utils.single_movie_info(movie_id=i['tmdb'],cache_time=7)
			try:
				if contains_non_english(movie_info['original_title']):
					original_title = movie_info['title']
				else:
					original_title = movie_info['original_title']
			except:
				try: original_title = movie_info['title']
				except: continue
			if original_title[:4].upper() in ['CON ', 'PRN ', 'AUX ', 'NUL ']:
				original_title = Utils.make_safe_filename(original_title)
				original_title = '.' + original_title 
			else:
				original_title = Utils.make_safe_filename(original_title)
			if '4K' in i['name']:
				flag_4k = True
			else:
				flag_4k = False
			#strm_movie_folder = '/%s.(%s).[tmdb=%s]' % (original_title, str(movie_info['release_date'][:4]), str(i['tmdb']))
			if flag_4k:
				strm_movie_path = '%s.(%s).[tmdb=%s][4k]/%s.(%s).[tmdb=%s][4k].strm' % (original_title, str(movie_info['release_date'][:4]), str(i['tmdb']), original_title, str(movie_info['release_date'][:4]), str(i['tmdb']))
			else:
				strm_movie_path = '%s.(%s).[tmdb=%s]/%s.(%s).[tmdb=%s].strm' % (original_title, str(movie_info['release_date'][:4]), str(i['tmdb']), original_title, str(movie_info['release_date'][:4]), str(i['tmdb']))
			strm_movie_path = os.path.join(str(MOVIES_DIR),strm_movie_path)
			xml_movie_nfo_path = strm_movie_path.replace('.strm','.nfo')
			nfo_movie_path = os.path.join(MOVIES_DIR, '%s.(%s).[tmdb=%s]/movie.nfo' % (original_title, str(movie_info['release_date'][:4]), str(i['tmdb'])))
			nfo_url = 'https://www.themoviedb.org/movie/%s' % (str(i['tmdb']))

			strm_url = f"{SERVER_ADD}/movie/{USERNAME}/{PASSWORD}/{i['stream_id']}.{i['container_extension']}"
			with safe_open_w(strm_movie_path) as f:
				f.write(strm_url)
			with safe_open_w(nfo_movie_path) as f:
				f.write(nfo_url)
			xml = kodi_movie_nfo(movie_info)
			with safe_open_w(xml_movie_nfo_path) as f:
				f.write(xml)
			result_list.append(strm_movie_path)
			result_list.append(nfo_movie_path)
			result_list.append(nfo_url)
			result_list.append(strm_url)
			result_list.append(xml)

			cache_dict['id'], cache_dict['tmdb_id'], cache_dict['added'], cache_dict['container_ext'],cache_dict['title'], cache_dict['strm_path'] = i['stream_id'], i['tmdb'], i['added'], i['container_extension'],check_title, strm_movie_path
			cache_dict['kodi_added'] = int(time.time())
			cache_dict['media_type'] = 'MOVIE'
			cache_dict['updated'] = i['added']
			log_to_kodi(cache_dict)
			db_update(cache_dict)
			log_to_kodi(f"Created: {strm_movie_path}")

#check_db_missing_on_json2()
#exit()


def sort_nested(data, sort_key, asc=True):
	# Helper to recursively find the sort_key in nested structures
	def find_key(obj):
		if isinstance(obj, dict):
			if sort_key in obj:
				return obj[sort_key]
			for value in obj.values():
				result = find_key(value)
				if result is not None:
					return result
		elif isinstance(obj, list):
			for item in obj:
				result = find_key(item)
				if result is not None:
					return result
		return None

	# Determine if input is a list or dict and sort accordingly
	if isinstance(data, dict):
		sorted_items = sorted(data.items(), key=lambda item: find_key(item[1]), reverse=not asc)
		return dict(sorted_items)
	elif isinstance(data, list):
		return sorted(data, key=lambda item: find_key(item), reverse=not asc)
	else:
		raise TypeError("Input must be a list or dictionary")
 




vod_TV = VOD_json(SERIES_API_URL)
vod_TV = sort_nested(vod_TV,'last_modified',False)
#for ix, i in enumerate(vod_TV):
#	print(i['name'])
#	print(i['last_modified'])
#	if ix > 100:
#		break


vod_movie = VOD_json(VOD_API_URL)
vod_movie = sort_nested(vod_movie,'added',False)
#for ix, i in enumerate(vod_movie):
#	print(i['name'])
#	print(i['added'])
#	if ix > 100:
#		break
#exit()

#vod_TV = VOD_json(SERIES_API_URL)
#vod_movie = VOD_json(VOD_API_URL)
tv_create_strm(vod_TV)
movie_create_strm(vod_movie)

def main():
	return

if __name__ == '__main__':
	main()
