import sys
import os

# Ensure bundled libs take priority
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), 'resources', 'lib'))

from kodi_stubs import xbmcaddon as xbmcaddon
from kodi_stubs import xbmcgui as xbmcgui
from kodi_stubs import xbmcvfs as xbmcvfs
from kodi_stubs import xbmcplugin as xbmcplugin
from kodi_stubs import xbmcdrm as xbmcdrm

import types
import tempfile

# --- xbmc ---
xbmc = types.ModuleType("xbmc")
xbmc.LOGDEBUG = 0
xbmc.LOGINFO = 1
xbmc.LOGWARNING = 2
xbmc.LOGERROR = 3
xbmc.LOGFATAL = 4
xbmc.LOGNONE = 5

xbmc.log = lambda msg, level=xbmc.LOGDEBUG: print(f"[xbmc log - level {level}]: {msg}")
xbmc.getInfoLabel = lambda label: f"Mocked info for {label}"
xbmc.getCondVisibility = lambda cond: True
xbmc.getLanguage = lambda default=False, region=False: "en"
xbmc.getSkinDir = lambda: "default"
xbmc.getLocalizedString = lambda id: f"Localized string {id}"
xbmc.executebuiltin = lambda command, wait=False: print(f"[xbmc.executebuiltin] {command} (wait={wait})")
xbmc.executeJSONRPC = lambda query: f"Mocked JSONRPC response for: {query}"
xbmc.getRegion = lambda key: "US"
xbmc.getUserAgent = lambda: "Kodi/20.0 (Linux; Android 9)"
xbmc.sleep = lambda ms: str(f"[xbmc.sleep] Sleeping for {ms}ms")
xbmc.getProperty = lambda key: f"Mocked property for {key}"
xbmc.setProperty = lambda key, value: print(f"[xbmc.setProperty] {key} = {value}")


class Monitor:
	def waitForAbort(self, timeout=0): return False
	def abortRequested(self): return False
xbmc.Monitor = Monitor


def set_setting(setting_name, setting_value, SETTING_XML):
	#setting_line = '    <setting id="%s">%s</setting>' % (setting_name, setting_value)
	new_setting_file = ''
	update = False
	with open(SETTING_XML) as f:
		lines = f.readlines()
		for line in lines:
			if setting_name in str(line):
				line_split_1 = line.split('"')[0] + '"'
				line_split_2 = setting_name
				line_split_3 = '"' + line.split('"',2)[2].split('>')[0] + '>'
				line_split_4 = setting_value
				try: line_split_5 = '<' + line.split('"',2)[2].split('<')[1]
				except: line_split_5 = '</setting>\n'
				setting_line = str(line_split_1) + str(line_split_2) + str(line_split_3) + str(line_split_4) + str(line_split_5)
				setting_line = setting_line.replace('default="true" />','default="true">')
				setting_line = setting_line.replace(' />','>')
				new_setting_file = new_setting_file + setting_line
				if setting_line != line:
					update = True
			else:
				new_setting_file = new_setting_file + line
	if update == True:
		with open(SETTING_XML, 'w') as file:
			# Write new content to the file
			file.write(new_setting_file)

def get_setting(setting_name, SETTING_XML,var_type = 'string'):
	return_var = None
	setting_name = setting_name + '"'

	with open(SETTING_XML) as f:
		lines = f.readlines()
		for line in lines:
			if setting_name in str(line):
				return_var = line.split('>')[1].split('</')[0]
	if var_type == 'string':
		return_var = str(return_var)
	elif var_type == 'bool':
		if str(return_var).lower() == 'true':
			return_var = True
		if str(return_var).lower() == 'false':
			return_var = False
	elif var_type == 'int':
		return_var = int(return_var)
	elif var_type == 'float':
		return_var = float(return_var)
	return return_var


# Inject into sys.modules
sys.modules["xbmc"] = xbmc
sys.modules["xbmcaddon"] = xbmcaddon
sys.modules["xbmcgui"] = xbmcgui
sys.modules["xbmcvfs"] = xbmcvfs
sys.modules["xbmcplugin"] = xbmcplugin
sys.modules["xbmcdrm"] = xbmcdrm