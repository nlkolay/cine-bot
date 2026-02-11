from dataclasses import dataclass

import aiohttp

from config import TMDB_API_KEY

BASE_URL = "https://api.themoviedb.org/3"


@dataclass
class MediaResult:
    title: str
    year: str
    tmdb_id: int
    imdb_id: str | None
    media_type: str  # "movie" or "tv"

    @property
    def tmdb_link(self) -> str:
        return f"https://www.themoviedb.org/{self.media_type}/{self.tmdb_id}"

    @property
    def imdb_link(self) -> str | None:
        if self.imdb_id:
            return f"https://www.imdb.com/title/{self.imdb_id}"
        return None

    @property
    def trakt_link(self) -> str | None:
        if self.imdb_id:
            return f"https://trakt.tv/search/imdb/{self.imdb_id}"
        return None


async def _get_imdb_id(session: aiohttp.ClientSession, media_type: str, tmdb_id: int) -> str | None:
    """Fetch imdb_id via external_ids endpoint."""
    url = f"{BASE_URL}/{media_type}/{tmdb_id}/external_ids"
    params = {"api_key": TMDB_API_KEY}
    async with session.get(url, params=params) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        return data.get("imdb_id") or None


async def _search_type(session: aiohttp.ClientSession, title: str, media_type: str) -> MediaResult | None:
    """Search TMDb for a title in a specific media type."""
    url = f"{BASE_URL}/search/{media_type}"
    params = {"api_key": TMDB_API_KEY, "query": title, "language": "en-US", "page": 1}
    async with session.get(url, params=params) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()

    results = data.get("results")
    if not results:
        return None

    item = results[0]
    tmdb_id = item["id"]

    if media_type == "movie":
        name = item.get("title", title)
        date = item.get("release_date", "")
    else:
        name = item.get("name", title)
        date = item.get("first_air_date", "")

    year = date[:4] if date else ""

    imdb_id = await _get_imdb_id(session, media_type, tmdb_id)

    return MediaResult(
        title=name,
        year=year,
        tmdb_id=tmdb_id,
        imdb_id=imdb_id,
        media_type=media_type,
    )


async def search(title: str) -> MediaResult | None:
    """Search TMDb for a movie first, then TV show."""
    async with aiohttp.ClientSession() as session:
        result = await _search_type(session, title, "movie")
        if result:
            return result
        return await _search_type(session, title, "tv")
