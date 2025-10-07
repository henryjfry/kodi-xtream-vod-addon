DONT USE THIS ADDON - attempted to get it to work well for Kodi but testing determined that local libraries of this size are prohibitively expensive.
Cached data lookups balloon DB to 100's mbs if not larger and thats before Kodi would add them to its library.
Attempts to circumvent kodi scraping also failed and writing to the DB directly is not an option.

Average VOD library will have far too many strm files to do all metadata lookups, cache this information, not cache this information, not crash kodi once it attempts to process 20000+ STRM files in one go.
Only other option is to have your video library slowly populate over a week or something but thats not exactly ideal.

VOD on demand lookups are the only thing which will work but regular kodi video addons suck at this.
In fact the Kodi media db just suck generally and is slow at loading in its own XML screens.

Kodi devs clearly have kodi running on PCs and obviously dont mind expensive lookups.

Thats the only explanation how loading 20 listitems on a video addon screen takes as long as it takes when all the information is all already cached locally.

Therefore need to be running in a script addon which doesnt close and reopen all the windows and doesnt stop running in between times to get blocked by kodi blocking functions:

https://github.com/henryjfry/repository.thenewdiamond/tree/main/script.xtreme_vod

This type of addon is the only viable way of using VOD on kodi, in my opinion.

