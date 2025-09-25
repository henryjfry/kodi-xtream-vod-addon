import os, re, time, json, hashlib, requests, sys
#import threading
from datetime import datetime
from datetime import date


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

ADDON,SERVER_ADD,USERNAME,PASSWORD,MOVIES_DIR,TVSHOWS_DIR,SPORT_DIR,TMDB_API_KEY, WORKING_DIR = None,None,None,None,None,None,None, None,None
SETTING_XML = r"C:\Users\philipshaw\Downloads\setting.xml"

def util_variables(xbmc_flag):
	import kodi_stub
	global ADDON,SERVER_ADD,USERNAME,PASSWORD,MOVIES_DIR,TVSHOWS_DIR,SPORT_DIR,TMDB_API_KEY, WORKING_DIR
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
	return xbmc_flag


def folder_exists(folder_path):
	if not os.path.exists(folder_path):
		os.makedirs(folder_path, exist_ok=True)
	return

xbmc_flag = util_variables(xbmc_flag)
try: test = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
except: test = ''

if len(test) == 0 and xbmc_flag:
	xbmc_flag = False
	xbmc_flag = util_variables(xbmc_flag)

if xbmc_flag:
	CACHE_DIR = os.path.join(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')), 'cache')
else:
	CACHE_DIR = os.path.join(WORKING_DIR, 'cache')


CACHE_PATH = os.path.join(CACHE_DIR,'xtream_cache2.sqlite')
#from inspect import currentframe, getframeinfo

folder_exists(WORKING_DIR)
folder_exists(TVSHOWS_DIR)
folder_exists(MOVIES_DIR)
folder_exists(CACHE_DIR)

def log_to_kodi(msg):
	if xbmc_flag:
		xbmc.log(f"[m3utostrm] {msg}", xbmc.LOGINFO)
	else:
		print(f"[m3utostrm] {msg}")


db_con = None
def test_db():
	import sqlite3
	db_con = sqlite3.connect(CACHE_PATH, check_same_thread=False)
	return db_con

def encode_db(sample_string):
	import base64
	sample_string_bytes = sample_string.encode("ascii")
	base64_bytes = base64.b64encode(sample_string_bytes)
	base64_string = base64_bytes.decode("ascii")
	return base64_string

def decode_db(base64_string):
	import base64
	base64_bytes = base64_string.encode("ascii")
	sample_string_bytes = base64.b64decode(base64_bytes)
	sample_string = sample_string_bytes.decode("ascii")
	return sample_string

def clear_db(connection=None,table_name=None):
	if db_con == None:
		connection = db_start()
	cur = connection.cursor()
	#[('Trakt',), ('TheMovieDB',), ('rss',), ('IMDB',), ('TasteDive',), ('FanartTV',), ('YouTube',), ('TVMaze',), ('show_filters',), ('Google',)]
	#dbfile = '/home/osmc/.kodi/userdata/addon_data/script.extendedinfo/cache.db'
	#con = sqlite3.connect(dbfile)
	#cur = con.cursor()

	table_list = [a for a in cur.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
	for i in table_list:
		#cur.execute("SELECT * from %s" % (i)).fetchall()
		if table_name:
			i = table_name#
		log_to_kodi(str(i))
		result = cur.execute('SELECT * FROM %s' % (i)).fetchall()
		log_to_kodi(str(len(result)))
		cur.execute('DELETE FROM %s' % (i))
		log_to_kodi(str('DELETE FROM %s ' % (i))) 
		if table_name:
			break
	connection.commit()
	cur.execute('VACUUM')
	cur.close()



def write_db(connection=None,url=None, cache_days=7.0, folder=False,cache_val=None, headers=False):
	if db_con == None:
		connection = db_start()
	try: cur = connection.cursor()
	except: connection = db_start()
	try: url = url.encode('utf-8')
	except: pass
	hashed_url = hashlib.md5(url).hexdigest()
	cache_seconds = int(cache_days * 86400.0)
	if isinstance(cache_val, str) == True:
		cache_val = encode_db(cache_val)
		cache_type = 'str'
	elif isinstance(cache_val, list) == True or isinstance(cache_val, dict) == True:
		try: 
			cache_val = encode_db(json.dumps(cache_val))
			cache_type = 'json'
		except: 
			cache_val = encode_db(str(cache_val))
			cache_type = 'list'

	expire = round(time.time() + cache_seconds,0)
	sql_query = """
	CREATE TABLE IF NOT EXISTS %s (
		url VARCHAR PRIMARY KEY,
		cache_val BLOB NOT NULL,
		cache_type VARCHAR NOT NULL,
		expire INT NOT NULL
	); 
	""" % (folder)
	sql_result = cur.execute(sql_query).fetchall()
	try: 
		connection.commit()
	except:
		connection.commit()
	sql_query = """
	INSERT INTO %s (url,cache_val,cache_type,expire)
	VALUES( '%s','%s','%s',%s);
	""" % (folder, hashed_url,cache_val,cache_type,int(expire))
	try: 
		sql_result = cur.execute(sql_query).fetchall()
	except Exception as ex:
		if 'UNIQUE constraint failed' in str(ex):
			sql_query = """
			REPLACE INTO %s (url,cache_val,cache_type,expire)
			VALUES( '%s','%s','%s',%s);
			""" % (folder, hashed_url,cache_val,cache_type,int(expire))
			sql_result = cur.execute(sql_query).fetchall()
	try: 
		connection.commit()
	except:
		try: connection.commit()
		except: pass
	cur.close()

def query_db(connection=None,url=None, cache_days=7.0, folder=False, headers=False):
	if db_con == None:
		connection = db_start()
	cur = connection.cursor()
	try: url = url.encode('utf-8')
	except: pass
	cache_val = None
	cache_seconds = int(cache_days * 86400.0)
	hashed_url = hashlib.md5(url).hexdigest()

	sql_query = """select cache_val, expire,cache_type from %s
	where url = '%s'
	""" % (folder, hashed_url)


	try: 
		sql_result = cur.execute(sql_query).fetchall()
	except Exception as ex:
		if 'no such table' in str(ex):
			return None
		else:
			xbmc.log(str(ex)+'===>OPENINFO', level=xbmc.LOGINFO)
	if len(sql_result) ==0:
		cur.close()
		return None

	expire = round(time.time() + cache_seconds,0)
	if int(time.time()) >= int(sql_result[0][1]) or expire <= int(sql_result[0][1]) :
		sql_query = """DELETE FROM %s
		where url = '%s'
		""" % (folder, hashed_url)
		sql_result = cur.execute(sql_query).fetchall()
		connection.commit()
		cur.close()
		return None
	else:
		cache_type = sql_result[0][2]
		if cache_type == 'str':
			cache_val = decode_db(sql_result[0][0])
		elif cache_type == 'list':
			cache_val = eval(decode_db(sql_result[0][0]))
		elif cache_type == 'json':
			cache_val = json.loads(decode_db(sql_result[0][0]))
		cur.close()
		return cache_val

def db_delete_expired(connection=None):
	if db_con == None:
		connection = db_start()
	cur = connection.cursor()
	curr_time = int(time.time())
	sql_query = """SELECT * FROM sqlite_master WHERE type='table'
	"""  
	sql_result = cur.execute(sql_query).fetchall()
	log_to_kodi('DELETE____')
	for i in sql_result:
		folder = i[1]
		sql_query = """select * FROM %s
		where expire < %s
		""" %  (folder, curr_time)
		sql_result1 = cur.execute(sql_query).fetchall()
		if len(sql_result1) == 0:
			continue
		log_to_kodi(folder)
		sql_query = """DELETE FROM %s
		where expire < %s
		""" % (folder, curr_time)
		try:
			sql_result = cur.execute(sql_query).fetchall()
			log_to_kodi(str(len(sql_result1))+str(folder),'===>DELETED')
		except OperationalError:
			connection.commit()
			sql_result = cur.execute(sql_query).fetchall()
			log_to_kodi(str(len(sql_result1))+str(folder),'===>DELETED')
	connection.commit()
	try: cur.execute('VACUUM')
	except Exception as ex:
		if 'SQL statements in progress' in str(ex):
			return None
		else:
			xbmc.log(str(ex)+'===>OPENINFO', level=xbmc.LOGINFO)
	cur.close()
	log_to_kodi('DELETED')
	return None


db_start = test_db()
db_con = db_start

def get_http(url, headers=False):
	succeed = 0
	if not headers:
		headers = {'User-agent': 'Kodi/18.0 ( phil65@kodi.tv )'}
	while (succeed < 2) :
		try:
			request = requests.get(url, headers=headers)
			return request.text
		except Exception as e:
			log('get_http: could not get data from %s' % url)
			xbmc.sleep(500)
			succeed += 1
	return None


def get_tmdb_data(url='', cache_days=14, folder='TheMovieDB'):
	url = 'https://api.themoviedb.org/3/%sapi_key=%s' % (url, TMDB_API_KEY)
	return get_JSON_response(url, cache_days, folder)


def single_movie_info(movie_id=None, cache_time=14):
	if not movie_id:
		return None
	session_str = ''
	response = get_tmdb_data('movie/%s?append_to_response=credits,external_ids,release_dates,rating,alternative_titles,images&language=en&include_image_language=en&' % (movie_id), cache_time)
	return response

def single_tvshow_info(tvshow_id=None, cache_time=7, dbid=None):
	if not tvshow_id:
		return None
	response = get_tmdb_data('tv/%s?append_to_response=credits,external_ids,content_ratings,images,rating,alternative_titles&language=en&include_image_language=en&' % (tvshow_id), cache_time)
	return response

def extended_episode_info(tvshow_id, season, episode, cache_time=7):
	if not tvshow_id or not episode:
		return None
	if not season:
		season = 0
	tvshow = get_tmdb_data('tv/%s?append_to_response=credits,external_ids,content_ratings,images,rating,alternative_titles&language=en&include_image_language=en&' % (tvshow_id), 99999)
	response = get_tmdb_data('tv/%s/season/%s/episode/%s?append_to_response=credits,external_ids,images,content_ratings,runtime,rating&language=en&include_image_language=en&' % (tvshow_id, season, episode), cache_time)
	return response, tvshow

def get_JSON_response(url='', cache_days=7.0, folder=False, headers=False):
	now = time.time()
	url = url.encode('utf-8')
	hashed_url = hashlib.md5(url).hexdigest()
	cache_seconds = int(cache_days * 86400.0)

	try: 
		db_result = query_db(connection=db_con,url=url, cache_days=cache_days, folder=folder, headers=headers)
	except:
		db_result = None
	if db_result:
		return db_result
	else:
		response = get_http(url, headers)
		try: results = json.loads(response)
		except: results = []
	if not results or len(results) == 0:
		return None
	else:
		write_db(connection=db_con,url=url, cache_days=cache_days, folder=folder,cache_val=results)
	return results


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


def is_title_a_year(title):
	"""Checks if a title string represents a year."""
	clean_title = title.strip()
	clean_title = re.sub(r'^\((\d{4})\)$', r'\1', clean_title) # Handle (YYYY) format
	return re.match(r'^\d{4}$', clean_title) is not None

def extract_title_and_year(title):
	"""
	Extracts the main title and year from a string, handling various patterns.
	This version is improved to better handle titles starting with numbers/years.
	"""
	original_title = title
	year = ""

	# 1. Extract year first using a robust pattern for (YYYY)
	year_match = re.search(r'\((\d{4})\)', title)
	if year_match:
		year = year_match.group(1)
		# Remove the extracted year and surrounding parentheses from the title
		title = re.sub(r'\s*\(\d{4}\)', '', title).strip()

	# 2. Remove common prefixes and suffixes that are not part of the main title
	# These patterns should be applied to the title *after* year extraction
	prefixes = [
		r'^[A-Z]{2,3}\s*[|]\s*', # e.g., "EN | "
		r'^[A-Z]{2,3}\s*[-]\s*', # e.g., "US - "
		r'^VOD\s*[|]\s*',
		r'^TV\s*[|]\s*',
		r'^\d+\.\s*', # e.g., "01. "
		r'^[A-Z0-9_]+:\s*', # e.g., "CHANNEL_NAME: "
		r'^[0-9]+\s*[|]\s*',
		r'^num":\s*\d+,\s*"name":\s*"',
		r'^[A-Z]{2,3}\s*:\s*'
	]
	for prefix_pattern in prefixes:
		title = re.sub(prefix_pattern, '', title).strip()

	# Remove season/episode info and country codes that might still be present
	# This is crucial for TV show titles like "1000-lb Sisters (US) S02 E01"
	title = re.sub(r'\s*\(US\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (US)
	title = re.sub(r'\s*\(GB\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (GB)
	title = re.sub(r'\s*\(AU\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (AU)
	title = re.sub(r'\s*\(TR\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (TR)
	title = re.sub(r'\s*\(JO\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (JO)
	title = re.sub(r'\s*\(CA\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (CA)
	title = re.sub(r'\s*\(KR\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (KR)
	title = re.sub(r'\s*\(ES\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (ES)
	title = re.sub(r'\s*\(JP\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (JP)
	title = re.sub(r'\s*\(ZA\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (ZA)
	title = re.sub(r'\s*\(IT\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (IT)
	title = re.sub(r'\s*\(CZ\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (CZ)
	title = re.sub(r'\s*\(BR\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (BR)
	title = re.sub(r'\s*\(AE\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (AE)
	title = re.sub(r'\s*\(DK\)\s*', '', title, flags=re.IGNORECASE).strip() # Specific for (DK)
	title = re.sub(r'\s*S\d{1,2}(?:E\d{1,2})?\s*', '', title, flags=re.IGNORECASE).strip() # S02 E01, S02
	title = re.sub(r'\s*E\d{1,2}\s*', '', title, flags=re.IGNORECASE).strip() # E01 if S is missing

	suffixes = [
		r'\s*\|.*$', # e.g., " | HD"
		r'\s*-\s*.*$', # e.g., " - Live"
		r'\s*"$' # Trailing quote
	]
	for suffix_pattern in suffixes:
		title = re.sub(suffix_pattern, '', title).strip()

	# Clean up multiple spaces and strip leading/trailing spaces
	clean_title = re.sub(r'\s+', ' ', title).strip()

	# If year wasn't found in (YYYY) format, try to find it as a standalone 4-digit number
	# but only if it's not part of a larger number like "1000-lb"
	if not year:
		# Look for a 4-digit number that is a whole word
		standalone_year_match = re.search(r'\b(\d{4})\b', clean_title)
		if standalone_year_match:
			year = standalone_year_match.group(1)
			# Remove the standalone year from the title
			clean_title = re.sub(r'\s*\b\d{4}\b', '', clean_title).strip()

	return clean_title, year


def remove_non_ascii(obj):
	from unidecode import unidecode
	"""Recursively remove non-ASCII characters from all strings in a dict/list/str structure."""
	if isinstance(obj, dict):
		return {remove_non_ascii(k): remove_non_ascii(v) for k, v in obj.items()}
	elif isinstance(obj, list):
		return [remove_non_ascii(i) for i in obj]
	elif isinstance(obj, str):
		return unidecode(obj)
	else:
		return obj

def make_safe_filename(s):
	def safe_char(c):
		if c.isalnum():
			return c
		else:
			return "."
	return "".join(safe_char(c) for c in s).rstrip(".")
