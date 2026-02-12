from html import escape

from telethon.tl.types import KeyboardButtonUrl

from tmdb_client import MediaResult


def format_result(r: MediaResult) -> str:
    """Format a single MediaResult into an HTML message."""
    lines: list[str] = []

    year_part = f" ({r.year})" if r.year else ""
    lines.append(f'\U0001f3ac <b>{escape(r.title)}{year_part}</b>')

    rt = r.ratings
    if rt:
        if rt.genre:
            lines.append(f"\U0001f3f7 {escape(rt.genre)}")

        scores: list[str] = []
        if rt.imdb:
            scores.append(f"IMDb {rt.imdb}")
        if rt.rotten:
            scores.append(f"RT {rt.rotten}")
        if rt.metacritic:
            scores.append(f"MC {rt.metacritic}")
        if scores:
            lines.append(f"\u2b50 {' \u00b7 '.join(scores)}")

        if rt.plot and rt.plot != "N/A":
            lines.append(f"\U0001f4dd {escape(rt.plot)}")

    return "\n".join(lines)


def format_source(source_text: str) -> str:
    """Format the original source message quote."""
    return f"\U0001f4ac \u2503 <blockquote>{escape(source_text.strip())}</blockquote>"


def build_buttons(r: MediaResult) -> list[list[KeyboardButtonUrl]]:
    """Build inline URL button row for a single result."""
    row: list[KeyboardButtonUrl] = []
    row.append(KeyboardButtonUrl(text="TMDb", url=r.tmdb_link))
    if r.imdb_link:
        row.append(KeyboardButtonUrl(text="IMDb", url=r.imdb_link))
    if r.trakt_link:
        row.append(KeyboardButtonUrl(text="Watchlist", url=r.trakt_link))
    return [row]
