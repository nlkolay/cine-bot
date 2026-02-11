from tmdb_client import MediaResult


def format_message(results: list[MediaResult]) -> str:
    """Format a list of MediaResult into an HTML message for Telegram."""
    blocks: list[str] = []

    for r in results:
        year_part = f" ({r.year})" if r.year else ""
        header = f'🎬 <b>{r.title}{year_part}</b>'

        links = [f'<a href="{r.tmdb_link}">TMDb</a>']
        if r.imdb_link:
            links.append(f'<a href="{r.imdb_link}">IMDb</a>')
        if r.trakt_link:
            links.append(f'<a href="{r.trakt_link}">Trakt.tv</a>')

        blocks.append(f"{header}\n\n📌 {' | '.join(links)}")

    return "\n\n".join(blocks)
