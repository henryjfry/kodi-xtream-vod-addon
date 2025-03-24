I am not a developer I just to like to have a dabble. This addon is for adding IPTV VOD content to the Kodi library using Xtream API logins (for legal IPTV services). This addon does not map tv channels only VOD. For TV Channels NextPVR is recommended. This addon does not provide any content, you must have a valid (legal) IPTV subscruption that allows Xtream API connections. I have made this addon for myself and as such will only be updating it if it breaks for me. Please do not ask for any fixes if it doesn't work for you. Feel free to download the code and fix / modify yourself or get an AI coder to do it for you.

Features:
Configurations screen:
    Server address (including port)
    Username
    Password
    Update frequency (in hours)
    Storage Location

To avoid constantly polling and dowanling from the Xtream server I have implemented a cache that will only refresh after a minumum of 24 hours, any shorter that this and you will likely recieve a ban from from your provider (trust me). To avoid further strain on the server and any other likely bans the addon does not automatically add episode data to your library. All available TV Shows will be added, if you want to add the episodes of a show or check for new content use the context menu (c) and select 'Fetch Episodes', if you spam this you will likely get banned by your provided as the episode data is a lot (trust me).

All movies and tv shows will integrate with the Kodi library allowing integration with the likes of Trakt and metadata scrapers. 
