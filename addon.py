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
from rapidfuzz import fuzz, process

"""
try:
	# --- Kodi APIs ---
	import xbmc
	import xbmcgui
	import xbmcaddon
	import xbmcvfs
	xbmc_flag = True
except:
	
	import kodi_stub
	from kodi_stubs import xbmcaddon as xbmcaddon
	from kodi_stubs import xbmcgui as xbmcgui
	from kodi_stubs import xbmcvfs as xbmcvfs
	from kodi_stubs import xbmcplugin as xbmcplugin
	from kodi_stubs import xbmcdrm as xbmcdrm
	from kodi_stubs import xbmc as xbmc
	xbmc_flag = False
"""

import Utils
from Utils import log_to_kodi as log_to_kodi
from Utils import remove_non_ascii as remove_non_ascii
xbmc_flag = Utils.xbmc_flag



"""
if xbmc_flag:
	# Kodi settings
	ADDON = xbmcaddon.Addon()
	SERVER_ADD = ADDON.getSetting('server_address')
	USERNAME = ADDON.getSetting('username')
	PASSWORD = ADDON.getSetting('password')
	MOVIES_DIR = ADDON.getSetting('movies_dir')
	TVSHOWS_DIR = ADDON.getSetting('tvshows_dir')
	SPORT_DIR = ADDON.getSetting('sport_dir') # Added SPORT_DIR
	TMDB_API_KEY = ADDON.getSetting('tmdb_api_key')
else:
	SERVER_ADD = kodi_stub.get_setting(setting_name = 'server_address', var_type = 'string', SETTING_XML=SETTING_XML)
	USERNAME = kodi_stub.get_setting(setting_name = 'username', var_type = 'string', SETTING_XML=SETTING_XML)
	PASSWORD = kodi_stub.get_setting(setting_name = 'password', var_type = 'string', SETTING_XML=SETTING_XML)
	MOVIES_DIR = kodi_stub.get_setting(setting_name = 'movies_dir', SETTING_XML=SETTING_XML)
	TVSHOWS_DIR = kodi_stub.get_setting(setting_name = 'tvshows_dir', var_type = 'string', SETTING_XML=SETTING_XML)
	SPORT_DIR = kodi_stub.get_setting(setting_name = 'sport_dir', var_type = 'string', SETTING_XML=SETTING_XML) # Added SPORT_DIR
	WORKING_DIR = kodi_stub.get_setting(setting_name = 'working_dir', var_type = 'string', SETTING_XML=SETTING_XML) # Added SPORT_DIR
	TMDB_API_KEY = kodi_stub.get_setting(setting_name = 'tmdb_api_key', var_type = 'string', SETTING_XML=SETTING_XML)
"""

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

session = CachedSession(cache_name=os.path.join(CACHE_DIR,'xtream_cache'), backend='sqlite', expire_after=86400)

def VOD_json(url, series_id=None):
	if series_id:
		url = get_series_info + '&series_id=%s' % str(i['series_id'])
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
	title = f"{tvshow.get('name', '')} - Season {season.get('season_number', '')}"
	plot = season.get("overview", "")
	year = season.get("air_date", "")[:4]
	tmdb_id = season.get("id", "")
	season_number = season.get("season_number", "")

	root = Element("season")
	SubElement(root, "title").text = title
	SubElement(root, "plot").text = plot
	SubElement(root, "season").text = str(season_number)
	SubElement(root, "year").text = year
	SubElement(root, "id").text = str(tmdb_id)
	SubElement(root, "tvshowid").text = str(tvshow.get("id", ""))

	xml_str = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + tostring(root, encoding="utf-8").decode()
	return xml_str

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



update_LIVE()
update_VOD()
vod_TV = VOD_json(SERIES_API_URL)
"""
for i in vod_TV:
	if 'Homicide' in str(i):
		print(i)
		vod_series = VOD_json(get_series_info,series_id=i['series_id'])
		print(vod_series)
		exit()

	vod_series = VOD_json(get_series_info,series_id=i['series_id'])
	#print(vod_series)
	for j in vod_series['seasons']:
		curr_season = str(j['season_number'])
		for jx in vod_series['episodes'][curr_season]:
			print(jx)
			strm_url = f"{SERVER_ADD}/series/{USERNAME}/{PASSWORD}/{jx['id']}.{jx['container_extension']}"
			episode_info, tvshow = Utils.extended_episode_info(tvshow_id=i['tmdb'],season=j['season_number'],episode=jx['episode_num'],cache_time=7)
			print(episode_info)
			print(tvshow)
			print(strm_url)

"""

for i in vod_TV:
	vod_series = VOD_json(get_series_info, series_id=i['series_id'])
	log_to_kodi(i['name'])
	if not vod_series or 'seasons' not in vod_series or 'episodes' not in vod_series:
		continue

	for j in vod_series['seasons']:
		curr_season = str(j['season_number'])
		if curr_season not in vod_series['episodes']:
			continue

		for jx in vod_series['episodes'][curr_season]:
			strm_url = f"{SERVER_ADD}/series/{USERNAME}/{PASSWORD}/{jx['id']}.{jx['container_extension']}"
			episode_info, tvshow = Utils.extended_episode_info(tvshow_id=i['tmdb'], season=j['season_number'], episode=jx['episode_num'], cache_time=7)

			try:
				if contains_non_english(tvshow['original_name']):
					original_title = tvshow['name']
				else:
					original_title = tvshow['original_name']
			except:
				try:
					original_title = tvshow['name']
				except:
					continue

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
				f.write(kodi_episode_nfo(episode_info, tvshow))

			with safe_open_w(xml_tvshow_nfo_path) as f:
				f.write(kodi_tvshow_nfo(tvshow))

			with safe_open_w(xml_season_nfo_path) as f:
				f.write(kodi_season_nfo(j, tvshow))

			log_to_kodi(f"Created: {strm_episode_path}")
	break
print(episode_info, tvshow)


vod_json = VOD_json(VOD_API_URL)
for i in vod_json:
	#log_to_kodi(i)
	if i['stream_type'] == 'movie':
		if i['tmdb'] == '':
			continue
		result_list = []
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
		
		log_to_kodi(xml)
	break

print(movie_info)

exit()


def main():
	return

if __name__ == '__main__':
	main()
