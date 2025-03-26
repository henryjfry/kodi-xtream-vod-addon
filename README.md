I am not a developer I just to like to have a dabble. This addon is for adding IPTV VOD content to the Kodi library using Xtream API logins (for legal IPTV services) by downloading and parsing M3U playlists and creating strm files in your chosen directories for movies and TV Shows. This addon does not map tv channels only VOD. For TV Channels NextPVR is recommended. This addon does not provide any content, you must have a valid (legal) IPTV subscruption that allows M3U connections. Even if you don't have Xtream API logins you can input the details for your provided M3U by stripping out your server address, username and password. I have made this addon for myself and as such will only be updating it if it breaks for me. Please do not ask for any fixes if it doesn't work for you. Feel free to download the code and fix / modify yourself or get an AI coder to do it for you.

Features:
Configurations screen:
    Directories
        Working directory, this is the directory that your log file and m3u list will be stored in, make sure Kodi has write access to the folder or you will recieve a permissions error
        Movies Directory, the directory you want to create your strm movie files in. This folder can then be added to your Kodi library
        TV Shows Directory, the directory you want to create your strm tv shows files in. This folder can then be added to your Kodi library
    Server Information
        Server address, can handle http and https depending on your provider
        username
        password
    Update Interval
        Days between updates, frequency to run the script
        Update time, time of day to run the script

**Note**
Due to the way that IPTV M3U's work the strm files will expose both your usernam and password, make sure you understand the implications of this before using the script

To avoid constantly polling and downloading from the server I have implemented a cache that will only refresh after a minumum of 24 hours, any shorter than this and you will likely recieve a ban from from your provider (trust me).

All movies and tv shows will integrate with the Kodi library allowing integration with the likes of Trakt and metadata scrapers. 

Tested on Ubuntu 24.04.2 LTS with Kodi 21.2 Omega as its written in Python3, depending on you Python setup you may need to add shedule to your packages. pip install schedule

To install, download the latest zip from the release section and manually install in Kodi Addons, Install from ZIP file
