from dataclasses import dataclass, field

import aiohttp

from config import TMDB_API_KEY
from extractor import TitleContext
from omdb_client import Ratings, fetch_ratings

BASE_URL = "https://api.themoviedb.org/3"

MIN_STEM_LEN = 4

# Lazy-loaded pymorphy3 (heavy import, only needed for Russian titles)
_morph = None


def _get_morph():
    global _morph
    if _morph is None:
        import pymorphy3
        _morph = pymorphy3.MorphAnalyzer()
    return _morph

# Common Russian to English movie title mappings for better People API matching
_TITLE_TRANSLATIONS = {
    'одержимый': ['Possession'],
    'одержимость': ['Possession'],
    'улыбка': ['Smile'],
    'вечность': ['Eternity', 'Forever'],
}


def _normalize_title(title: str) -> str:
    """Normalize Russian title to nominative case."""
    # Check if title contains Cyrillic characters
    if any('\u0400' <= c <= '\u04ff' for c in title):
        morph = _get_morph()
        words = title.split()
        normalized_words = []
        for word in words:
            parsed = morph.parse(word)[0]
            normalized_words.append(parsed.normal_form)
        return ' '.join(normalized_words)
    return title


def _get_title_variants(title: str) -> list[str]:
    """Get all possible title variants (original, normalized, translations)."""
    variants = [title]
    
    # Add normalized version
    normalized = _normalize_title(title)
    if normalized != title:
        variants.append(normalized)
    
    # Add English translations for normalized Russian titles
    if normalized in _TITLE_TRANSLATIONS:
        variants.extend(_TITLE_TRANSLATIONS[normalized])
    
    return list(dict.fromkeys(variants))  # Remove duplicates while preserving order


@dataclass
class MediaResult:
    title: str
    year: str
    tmdb_id: int
    imdb_id: str | None
    tvdb_id: int | None
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

async def _search_person(session: aiohttp.ClientSession, query: str) -> dict | None:
    """Search for a person by name."""
    url = f"{BASE_URL}/search/person"
    params = {"api_key": TMDB_API_KEY, "query": query, "language": "en-US", "page": 1}
    async with session.get(url, params=params) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
    
    results = data.get("results", [])
    return results[0] if results else None


async def _get_person_combined_credits(session: aiohttp.ClientSession, person_id: int) -> dict | None:
    """Get combined credits for a person."""
    url = f"{BASE_URL}/person/{person_id}/combined_credits"
    params = {"api_key": TMDB_API_KEY, "language": "en-US"}
    async with session.get(url, params=params) as resp:
        if resp.status != 200:
            return None
        return await resp.json()


def _fuzzy_title_match(query_title: str, candidate_title: str) -> bool:
    """Simple fuzzy title matching using stems."""
    query_stems = {_stem(w) for w in query_title.lower().split() if len(w) >= MIN_STEM_LEN}
    candidate_stems = {_stem(w) for w in candidate_title.lower().split() if len(w) >= MIN_STEM_LEN}
    
    # Exact match check (case insensitive)
    if query_title.lower() == candidate_title.lower():
        return True
    
    if not query_stems or not candidate_stems:
        return False
    
    # Consider it a match if at least 50% of query stems are in candidate stems
    overlap = len(query_stems & candidate_stems)
    return overlap >= len(query_stems) // 2 or overlap >= len(candidate_stems) // 2


def _title_match_score(query_title: str, candidate_title: str) -> int:
    """Calculate a score for title matching. Higher is better."""
    q_lower = query_title.lower()
    c_lower = candidate_title.lower()
    
    # Exact match gets highest score
    if q_lower == c_lower:
        return 100
    
    # Query contains candidate or vice versa
    if q_lower in c_lower or c_lower in q_lower:
        return 80
    
    # Fuzzy match score based on stem overlap
    query_stems = {_stem(w) for w in q_lower.split() if len(w) >= MIN_STEM_LEN}
    candidate_stems = {_stem(w) for w in c_lower.split() if len(w) >= MIN_STEM_LEN}
    
    if not query_stems or not candidate_stems:
        return 0
    
    overlap = len(query_stems & candidate_stems)
    return (overlap * 100) // max(len(query_stems), len(candidate_stems))


async def _search_via_person_api(
    session: aiohttp.ClientSession, title: str, director: str
) -> MediaResult | None:
    """Search using People API approach: find person first, then their filmography."""
    # Get all title variants (original, normalized, translations)
    title_variants = _get_title_variants(title)
    
    # 1. Find the person
    person = await _search_person(session, director)
    if not person:
        return None
    
    # 2. Get their combined credits
    credits = await _get_person_combined_credits(session, person["id"])
    if not credits:
        return None
    
    # 3. Look for fuzzy title match in their filmography (both cast and crew)
    all_items = []
    
    # Add cast items
    for item in credits.get("cast", []):
        if item.get("media_type") in ("movie", "tv"):
            all_items.append(item)
    
    # Add crew items (directors, writers, etc.)
    for item in credits.get("crew", []):
        if item.get("media_type") in ("movie", "tv"):
            all_items.append(item)
    
    # Deduplicate by ID
    seen_ids = set()
    unique_items = []
    for item in all_items:
        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            unique_items.append(item)
    
    # 4. Look for fuzzy title match with scoring (try all title variants)
    best_match = None
    best_score = 0
    
    for item in unique_items:
        item_title = item.get("title") or item.get("name", "")
        # Try each title variant
        for variant in title_variants:
            if _fuzzy_title_match(variant, item_title):
                score = _title_match_score(variant, item_title)
                if score > best_score:
                    best_score = score
                    best_match = item
    
    if best_match:
        # Found the best match in their filmography
        details = await _get_details(session, best_match["media_type"], best_match["id"])
        if details:
            return await _build_result_from_details(session, details, best_match["media_type"])
    
    return None


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


def _extract_tvdb_id(details: dict) -> int | None:
    """Extract tvdb_id from details with appended external_ids."""
    ext = details.get("external_ids", {})
    tvdb = ext.get("tvdb_id")
    return int(tvdb) if tvdb else None


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
        tvdb_id = _extract_tvdb_id(details)
    else:
        imdb_id = None
        tvdb_id = None

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
        tvdb_id=tvdb_id,
        media_type=media_type,
        ratings=ratings,
    )


async def _build_result_from_details(
    session: aiohttp.ClientSession, details: dict, media_type: str,
) -> MediaResult:
    """Build a MediaResult from already-fetched details dict."""
    tmdb_id = details["id"]
    imdb_id = _extract_imdb_id(details)
    tvdb_id = _extract_tvdb_id(details)

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
        tvdb_id=tvdb_id,
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

    # Normalize the title for better matching
    normalized_title = _normalize_title(title)

    # If we have a director hint, try the People API approach first
    if director:
        result = await _search_via_person_api(session, title, director)
        if result:
            return result

    # Collect candidates from movie + tv typed searches
    langs = ("en-US", "ru-RU") if ctx.is_english else ("ru-RU", "en-US")
    candidates: list[dict] = []
    for lang in langs:
        for mt in ("movie", "tv"):
            # Try original title
            items = await _search_typed(session, title, mt, lang, year=year, limit=5)
            candidates.extend(items)
            # If no results, try normalized title
            if not candidates and normalized_title != title:
                items = await _search_typed(session, normalized_title, mt, lang, year=year, limit=5)
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

    # If we have a director hint, verify against credits (top 3 candidates) as fallback
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


async def _search_plain(
    session: aiohttp.ClientSession, title: str, *, is_english: bool = False,
) -> MediaResult | None:
    """search/multi with language priority based on title origin."""
    langs = ("en-US", "ru-RU") if is_english else ("ru-RU", "en-US")
    for lang in langs:
        item = await _search_multi(session, title, lang)
        if item:
            return await _build_result_from_item(session, item)
    return None


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

        return await _search_plain(session, ctx.title, is_english=ctx.is_english)
