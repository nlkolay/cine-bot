from dataclasses import dataclass

import aiohttp

from config import OMDB_API_KEY

OMDB_URL = "https://www.omdbapi.com/"


@dataclass
class Ratings:
    imdb: str | None = None       # e.g. "8.1/10"
    rotten: str | None = None     # e.g. "93%"
    metacritic: str | None = None # e.g. "78/100"
    genre: str | None = None
    plot: str | None = None


async def fetch_ratings(imdb_id: str) -> Ratings | None:
    """Fetch ratings, genre, and plot from OMDb by IMDb ID.

    Returns None if OMDB_API_KEY is not configured or the request fails.
    """
    if not OMDB_API_KEY or not imdb_id:
        return None

    params = {"apikey": OMDB_API_KEY, "i": imdb_id, "plot": "short"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(OMDB_URL, params=params) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
    except Exception:
        return None

    if data.get("Response") != "True":
        return None

    ratings = Ratings(genre=data.get("Genre"), plot=data.get("Plot"))

    for entry in data.get("Ratings", []):
        source = entry.get("Source", "")
        value = entry.get("Value", "")
        if source == "Internet Movie Database":
            ratings.imdb = value
        elif source == "Rotten Tomatoes":
            ratings.rotten = value
        elif source == "Metacritic":
            ratings.metacritic = value

    return ratings
