from dataclasses import dataclass, field

import aiohttp

from config import TMDB_API_KEY
from extractor import TitleContext
from omdb_client import Ratings, fetch_ratings

BASE_URL = "https://api.themoviedb.org/3"

MIN_STEM_LEN = 4


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stem(word: str) -> str:
    """Crude stem: lowercase first MIN_STEM_LEN chars."""
    return word.lower()[:MIN_STEM_LEN]


def _names_match(query_name: str, candidate_name: str) -> bool:
    """Compare names by 4-char stems to handle Russian declensions.

    E.g. "Павла Лунгина" vs "Павел Лунгин" → stems "павл"+"лунг" match.
    """
    q_stems = {_stem(w) for w in query_name.split() if len(w) >= MIN_STEM_LEN}
    c_stems = {_stem(w) for w in candidate_name.split() if len(w) >= MIN_STEM_LEN}
    if not q_stems or not c_stems:
        return False
    return q_stems <= c_stems or c_stems <= q_stems


# ---------------------------------------------------------------------------
# TMDb API calls
# ---------------------------------------------------------------------------

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


async def _search_typed(
    session: aiohttp.ClientSession,
    title: str,
    media_type: str,
    language: str,
    year: int | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search for movie or tv specifically, with optional year filter."""
    url = f"{BASE_URL}/search/{media_type}"
    params: dict = {
        "api_key": TMDB_API_KEY,
        "query": title,
        "language": language,
        "page": 1,
    }
    if year is not None:
        if media_type == "movie":
            params["year"] = year
        else:
            params["first_air_date_year"] = year

    async with session.get(url, params=params) as resp:
        if resp.status != 200:
            return []
        data = await resp.json()

    results = []
    for item in data.get("results", [])[:limit]:
        item["media_type"] = media_type
        results.append(item)
    return results


async def _get_details(
    session: aiohttp.ClientSession, media_type: str, tmdb_id: int,
) -> dict | None:
    """Fetch details with credits and external_ids in one call."""
    url = f"{BASE_URL}/{media_type}/{tmdb_id}"
    params = {
        "api_key": TMDB_API_KEY,
        "append_to_response": "credits,external_ids",
    }
    async with session.get(url, params=params) as resp:
        if resp.status != 200:
            return None
        return await resp.json()


def _get_directors(details: dict, media_type: str) -> list[str]:
    """Extract director names from details['credits']."""
    credits = details.get("credits", {})
    if media_type == "movie":
        crew = credits.get("crew", [])
        return [p["name"] for p in crew if p.get("job") == "Director"]
    else:
        # For TV, use "created_by" from top-level details
        created_by = details.get("created_by", [])
        return [p["name"] for p in created_by]


def _extract_imdb_id(details: dict) -> str | None:
    """Extract imdb_id from details with appended external_ids."""
    ext = details.get("external_ids", {})
    return ext.get("imdb_id") or None


# ---------------------------------------------------------------------------
# Result building
# ---------------------------------------------------------------------------

async def _build_result_from_item(session: aiohttp.ClientSession, item: dict) -> MediaResult:
    """Build a MediaResult from a search item, using append_to_response for details."""
    media_type = item["media_type"]
    tmdb_id = item["id"]

    details = await _get_details(session, media_type, tmdb_id)

    if details:
        imdb_id = _extract_imdb_id(details)
    else:
        imdb_id = None

    if media_type == "movie":
        name = item.get("original_title") or item.get("title", "")
        date = item.get("release_date", "")
    else:
        name = item.get("original_name") or item.get("name", "")
        date = item.get("first_air_date", "")

    year = date[:4] if date else ""
    ratings = await fetch_ratings(imdb_id) if imdb_id else None

    return MediaResult(
        title=name,
        year=year,
        tmdb_id=tmdb_id,
        imdb_id=imdb_id,
        media_type=media_type,
        ratings=ratings,
    )


async def _build_result_from_details(
    session: aiohttp.ClientSession, details: dict, media_type: str,
) -> MediaResult:
    """Build a MediaResult from already-fetched details dict."""
    tmdb_id = details["id"]
    imdb_id = _extract_imdb_id(details)

    if media_type == "movie":
        name = details.get("original_title") or details.get("title", "")
        date = details.get("release_date", "")
    else:
        name = details.get("original_name") or details.get("name", "")
        date = details.get("first_air_date", "")

    year = date[:4] if date else ""
    ratings = await fetch_ratings(imdb_id) if imdb_id else None

    return MediaResult(
        title=name,
        year=year,
        tmdb_id=tmdb_id,
        imdb_id=imdb_id,
        media_type=media_type,
        ratings=ratings,
    )


# ---------------------------------------------------------------------------
# Search with context (fallback chain)
# ---------------------------------------------------------------------------

async def _search_with_context(
    session: aiohttp.ClientSession, ctx: TitleContext,
) -> MediaResult | None:
    """Search using year/director context. Fallback: year only → no context."""
    title = ctx.title
    year = ctx.year
    director = ctx.director

    # Collect candidates from movie + tv typed searches
    candidates: list[dict] = []
    for lang in ("ru-RU", "en-US"):
        for mt in ("movie", "tv"):
            items = await _search_typed(session, title, mt, lang, year=year, limit=5)
            candidates.extend(items)
        if candidates:
            break

    if not candidates:
        return None

    # Deduplicate by (media_type, id)
    seen: set[tuple[str, int]] = set()
    unique: list[dict] = []
    for item in candidates:
        key = (item["media_type"], item["id"])
        if key not in seen:
            seen.add(key)
            unique.append(item)

    # If we have a director hint, verify against credits (top 3 candidates)
    if director:
        for item in unique[:3]:
            details = await _get_details(session, item["media_type"], item["id"])
            if not details:
                continue
            directors = _get_directors(details, item["media_type"])
            if any(_names_match(director, d) for d in directors):
                return await _build_result_from_details(session, details, item["media_type"])

        # Director didn't match any — fall through to best candidate by popularity

    # Return best candidate (first = most popular from TMDb)
    return await _build_result_from_item(session, unique[0])


async def _search_plain(session: aiohttp.ClientSession, title: str) -> MediaResult | None:
    """Original search/multi behavior: ru-RU first, then en-US."""
    item = await _search_multi(session, title, "ru-RU")
    if not item:
        item = await _search_multi(session, title, "en-US")
    if not item:
        return None
    return await _build_result_from_item(session, item)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search(ctx: TitleContext) -> MediaResult | None:
    """Search TMDb with optional year/director context.

    Fallback chain:
    1. year + director context → typed search + director verification
    2. year only → typed search
    3. no context → search/multi (original behavior)
    """
    async with aiohttp.ClientSession() as session:
        if ctx.year or ctx.director:
            result = await _search_with_context(session, ctx)
            if result:
                return result
            # Context search failed — fall back to plain search

        return await _search_plain(session, ctx.title)
