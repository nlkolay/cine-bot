from dataclasses import dataclass, field

import aiohttp

from config import TMDB_API_KEY
from omdb_client import Ratings, fetch_ratings

BASE_URL = "https://api.themoviedb.org/3"


@dataclass
class MediaResult:
    title: str
    year: str
    tmdb_id: int
    imdb_id: str | None
    media_type: str  # "movie" or "tv"
    ratings: Ratings | None = field(default=None)

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


async def _search_multi(session: aiohttp.ClientSession, title: str, language: str) -> dict | None:
    """Run search/multi and return the first movie/tv result."""
    url = f"{BASE_URL}/search/multi"
    params = {"api_key": TMDB_API_KEY, "query": title, "language": language, "page": 1}
    async with session.get(url, params=params) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()

    for item in data.get("results", []):
        if item.get("media_type") in ("movie", "tv"):
            return item
    return None


async def _build_result(session: aiohttp.ClientSession, item: dict) -> MediaResult:
    """Build a MediaResult from a search/multi item."""
    media_type = item["media_type"]
    tmdb_id = item["id"]

    if media_type == "movie":
        name = item.get("original_title") or item.get("title", "")
        date = item.get("release_date", "")
    else:
        name = item.get("original_name") or item.get("name", "")
        date = item.get("first_air_date", "")

    year = date[:4] if date else ""

    imdb_id = await _get_imdb_id(session, media_type, tmdb_id)
    ratings = await fetch_ratings(imdb_id) if imdb_id else None

    return MediaResult(
        title=name,
        year=year,
        tmdb_id=tmdb_id,
        imdb_id=imdb_id,
        media_type=media_type,
        ratings=ratings,
    )


async def search(title: str) -> MediaResult | None:
    """Search TMDb using multi search; try ru-RU first, then en-US."""
    async with aiohttp.ClientSession() as session:
        item = await _search_multi(session, title, "ru-RU")
        if not item:
            item = await _search_multi(session, title, "en-US")
        if not item:
            return None
        return await _build_result(session, item)
