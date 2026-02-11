from html import escape

from tmdb_client import MediaResult


def format_message(results: list[MediaResult], source_text: str) -> str:
    """Format a list of MediaResult into an HTML message for Telegram."""
    parts: list[str] = []

    # Original message from source channel
    parts.append(f"💬 <blockquote>{escape(source_text.strip())}</blockquote>")

    for r in results:
        year_part = f" ({r.year})" if r.year else ""
        header = f'🎬 <b>{escape(r.title)}{year_part}</b>'

        links = [f'<a href="{r.tmdb_link}">TMDb</a>']
        if r.imdb_link:
            links.append(f'<a href="{r.imdb_link}">IMDb</a>')
        if r.trakt_link:
            links.append(f'<a href="{r.trakt_link}">Trakt.tv</a>')

        parts.append(f"{header}\n📌 {' | '.join(links)}")

    return "\n\n".join(parts)
