import re
from telethon.tl.types import MessageEntityBold


_QUOTE_PATTERN = re.compile(
    r'[«"„](.+?)[»""]'
)


def _is_valid_title(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    if text.startswith(("#", "http://", "https://")):
        return False
    word_count = len(text.split())
    return 2 <= word_count <= 10


def extract_titles(message) -> list[str]:
    """Extract movie/series titles from a Telegram message."""
    titles: list[str] = []
    text = message.raw_text or ""

    # 1. Quoted text
    for match in _QUOTE_PATTERN.finditer(text):
        candidate = match.group(1).strip()
        if _is_valid_title(candidate):
            titles.append(candidate)

    if titles:
        return titles

    # 2. Bold entities
    if message.entities:
        for entity in message.entities:
            if isinstance(entity, MessageEntityBold):
                candidate = text[entity.offset : entity.offset + entity.length].strip()
                if _is_valid_title(candidate):
                    titles.append(candidate)

    return titles
