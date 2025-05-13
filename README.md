# Kodi Xtream VOD Addon: IPTV VOD to Library

This Kodi addon allows you to seamlessly add IPTV Video-on-Demand (VOD) content to your Kodi library using Xtream API logins or a compatible M3U playlist. It parses your IPTV provider's M3U playlist and automatically generates `.strm` and `.nfo` files for movies and TV shows, enabling full Kodi library integration with metadata, artwork, and Trakt support.

> **This addon does not provide any content.** You must have a valid, legal IPTV subscription that allows M3U or Xtream API access.

---

## Version 2
- Significant code overhaul
- Added TMDb metadata creation (credit to [henryjfry](https://github.com/henryjfry))
- Improved Title detection
- Improved library scanning time, 20k plus files reduced from 48+ hours to 4 hours due to the implementation of TMDb nfo metadata
- **Becuause this is effectively a new code base it is recommended to delete all files created with any versions prior to 2.0. and clean your kodi library**
- Version 1 will still work if you want to continue to use it but will no longer be maintained 
---

## Features

- **Automatic VOD Library Integration:**
  - Parses IPTV M3U playlists and creates `.strm` and `.nfo` files for movies and TV shows.
  - Organises content into your chosen Movies and TV Shows directories for easy Kodi library scanning.
  - Fetches rich metadata and artwork from TMDb for a complete Kodi experience.
- **Configurable:**
  - Set working, movies, and TV shows directories.
  - Supports both Xtream API and direct M3U playlist URLs.
  - Adjustable update interval and time.
- **Efficient & Safe:**
  - 24-hour caching to avoid unnecessary downloads and reduce risk of provider bans.
  - Confirmation dialog before deleting files/folders.
  - Cleans all metadata and filenames to be ASCII-only for maximum compatibility.
- **No Live TV:**
  - This addon is for VOD only. For live TV channels, use [NextPVR](https://www.nextpvr.com/) or similar solutions.

---

## How It Works

1. **Configuration:**
   - Set your working, movies, and TV shows directories in the Kodi addon settings.
   - Enter your IPTV provider's server address, username, and password (Xtream API or M3U details).
   - Enter your TMDb API key, these can be created for free from [TMDb](https://developer.themoviedb.org/docs/getting-started)
2. **Fetching & Caching:**
   - The addon downloads your M3U playlist and caches it for 24 hours to minimise server load.
   - Series and VOD metadata are also cached for 24 hours.
3. **Parsing & File Generation:**
   - The M3U is parsed, and entries are matched to your provider's VOD/series catalog.
   - For each movie or TV episode, a `.strm` file (with the stream URL) and a Kodi-compatible `.nfo` file (with full metadata) are created in the appropriate directory.
   - TV shows are organised into folders by show and season.
4. **Kodi Library Integration:**
   - Add your Movies and TV Shows directories to Kodi as sources and scan them into your library.
   - Enjoy full metadata, artwork, and Trakt integration for your IPTV VOD content.

---

## Installation Instructions

1. **Install Python Requirements**
   - Download the [requirements.txt](https://github.com/Boc86/kodi-xtream-vod-addon/blob/main/requirements.txt) file.
   - Open a terminal in the folder where you downloaded `requirements.txt` and run:
     ```bash
     pip install -r requirements.txt
     ```
2. **Install the Addon**
   - Download the latest addon ZIP from the [Releases](https://github.com/Boc86/kodi-xtream-vod-addon/releases) page.
   - In Kodi, enable installation from unknown sources.
   - Go to **Add-ons > Install from zip file** and select the downloaded ZIP.
3. **Configure the Addon**
   - Open the addon settings and set your directories, IPTV credentials, and TMDb API Key.
   - Adjust update interval and time as desired.
4. **Add Sources to Kodi Library**
   - Add your Movies and TV Shows directories as sources in Kodi and scan them into your library.

---

## Important Notes

- **Security:**
  - The generated `.strm` files will contain your IPTV username and password in the stream URL. Make sure you understand the implications before using this addon and keep your library folders secure.
- **Caching:**
  - To avoid excessive polling and potential bans from your IPTV provider, the addon caches playlist and metadata for 24 hours. Do not reduce this interval.
- **No Content Provided:**
  - This addon does not provide any content. You must have a valid, legal IPTV subscription that allows M3U or Xtream API access.
- **Compatibility:**
  - All metadata and filenames are cleaned to be ASCII-only for maximum compatibility with Kodi and various filesystems.
- **Support:**
  - This addon is provided as-is. Please do not request support or fixes. Feel free to fork or modify the code for your own use.

---

## Tested On
- Ubuntu 24.04.2 LTS
- Fedora 41 & 42
- Kodi 21.2 Omega
- Python 3.x


Enjoy your IPTV VOD content fully integrated into your Kodi library!

Credit to [henryjfry](https://github.com/henryjfry) for pointing me in the direction of his repo and existing VOD work that has inspired the V2 re-write
