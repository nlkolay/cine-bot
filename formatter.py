from html import escape

from telethon.tl.types import KeyboardButtonUrl

from tmdb_client import MediaResult


def format_message(results: list[MediaResult], source_text: str) -> str:
    """Format a list of MediaResult into an HTML message for Telegram."""
    parts: list[str] = []

    if source_text.strip():
        parts.append(f"\U0001f4ac \u2503 <blockquote>{escape(source_text.strip())}</blockquote>")

    for r in results:
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

        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def build_buttons(results: list[MediaResult]) -> list[list[KeyboardButtonUrl]]:
    """Build inline URL button rows for each result."""
    rows: list[list[KeyboardButtonUrl]] = []

    for r in results:
        row: list[KeyboardButtonUrl] = []
        row.append(KeyboardButtonUrl(text="TMDb", url=r.tmdb_link))
        if r.imdb_link:
            row.append(KeyboardButtonUrl(text="IMDb", url=r.imdb_link))
        if r.trakt_link:
            row.append(KeyboardButtonUrl(text="Trakt", url=r.trakt_link))
        rows.append(row)

    return rows
