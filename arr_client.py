import logging

import aiohttp

from config import RADARR_URL, RADARR_API_KEY, SONARR_URL, SONARR_API_KEY

log = logging.getLogger(__name__)

# Cached quality profile + root folder per service
_radarr_defaults: dict | None = None
_sonarr_defaults: dict | None = None


async def _fetch_defaults(
    session: aiohttp.ClientSession, base_url: str, api_key: str,
) -> dict:
    """Fetch first quality profile ID and root folder path."""
    headers = {"X-Api-Key": api_key}

    async with session.get(f"{base_url}/api/v3/qualityprofile", headers=headers) as resp:
        profiles = await resp.json()
    profile_id = profiles[0]["id"] if profiles else 1

    async with session.get(f"{base_url}/api/v3/rootfolder", headers=headers) as resp:
        folders = await resp.json()
    root_path = folders[0]["path"] if folders else "/movies"

    return {"qualityProfileId": profile_id, "rootFolderPath": root_path}


async def add_to_radarr(tmdb_id: int, title: str) -> str:
    """Add a movie to Radarr by TMDb ID."""
    if not RADARR_URL or not RADARR_API_KEY:
        return "Radarr not configured"

    global _radarr_defaults
    base = RADARR_URL.rstrip("/")
    headers = {"X-Api-Key": RADARR_API_KEY}

    try:
        async with aiohttp.ClientSession() as session:
            if _radarr_defaults is None:
                _radarr_defaults = await _fetch_defaults(session, base, RADARR_API_KEY)

            payload = {
                "tmdbId": tmdb_id,
                "title": title,
                "qualityProfileId": _radarr_defaults["qualityProfileId"],
                "rootFolderPath": _radarr_defaults["rootFolderPath"],
                "monitored": True,
                "addOptions": {"searchForMovie": True},
            }

            async with session.post(
                f"{base}/api/v3/movie", json=payload, headers=headers,
            ) as resp:
                if resp.status == 201:
                    log.info("Added to Radarr: %s (tmdb=%d)", title, tmdb_id)
                    return "Added to Radarr ✅"
                body = await resp.json()
                log.error("Radarr error %d: %s", resp.status, body)
                if resp.status == 400:
                    msg = body[0].get("errorMessage", "") if isinstance(body, list) else str(body)
                    if "already" in msg.lower():
                        return "Already in Radarr"
                    return f"Radarr error: {msg}"
                return f"Radarr error ({resp.status})"
    except Exception as e:
        log.error("Radarr connection error: %s", e)
        return f"Radarr unavailable"


async def add_to_sonarr(tvdb_id: int, title: str) -> str:
    """Add a series to Sonarr by TVDB ID."""
    if not SONARR_URL or not SONARR_API_KEY:
        return "Sonarr not configured"

    global _sonarr_defaults
    base = SONARR_URL.rstrip("/")
    headers = {"X-Api-Key": SONARR_API_KEY}

    try:
        async with aiohttp.ClientSession() as session:
            if _sonarr_defaults is None:
                _sonarr_defaults = await _fetch_defaults(session, base, SONARR_API_KEY)

            payload = {
                "tvdbId": tvdb_id,
                "title": title,
                "qualityProfileId": _sonarr_defaults["qualityProfileId"],
                "rootFolderPath": _sonarr_defaults["rootFolderPath"],
                "monitored": True,
                "seasonFolder": True,
                "addOptions": {"searchForMissingEpisodes": True},
            }

            async with session.post(
                f"{base}/api/v3/series", json=payload, headers=headers,
            ) as resp:
                if resp.status == 201:
                    log.info("Added to Sonarr: %s (tvdb=%d)", title, tvdb_id)
                    return "Added to Sonarr ✅"
                body = await resp.json()
                if resp.status == 400:
                    msg = body[0].get("errorMessage", "") if isinstance(body, list) else str(body)
                    if "already" in msg.lower():
                        return "Already in Sonarr"
                    return f"Sonarr error: {msg}"
                return f"Sonarr error ({resp.status})"
    except Exception as e:
        log.error("Sonarr connection error: %s", e)
        return f"Sonarr unavailable"
