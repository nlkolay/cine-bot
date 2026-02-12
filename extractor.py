from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from telethon.tl.types import MessageEntityBold

if TYPE_CHECKING:
    from llm_client import LLMProvider

log = logging.getLogger(__name__)


@dataclass
class TitleContext:
    title: str
    year: int | None = None
    director: str | None = None
    is_english: bool = False


_QUOTE_PATTERN = re.compile(
    r'[«"„](.+?)[»""]'
)

_YEAR_PATTERN = re.compile(r'\b(19\d{2}|20[0-2]\d)\b')

# Capitalized name: 2-3 words, Cyrillic or Latin (but not mixed within one name)
_CYR_NAME = r'[А-ЯЁ][а-яё]+'
_LAT_NAME = r'[A-Z][a-z]+'
_CYR_FULLNAME = re.compile(rf'({_CYR_NAME}(?:\s+{_CYR_NAME}){{1,2}})')
_LAT_FULLNAME = re.compile(rf'({_LAT_NAME}(?:\s+{_LAT_NAME}){{1,2}})')

# Director keyword before a quoted title: режиссёр/режиссера + Name
_DIRECTOR_KEYWORD = re.compile(
    rf'(?:режисс[её]р[аы]?|[Сс]нявш[а-я]*)\s+({_CYR_NAME}(?:\s+{_CYR_NAME}){{1,2}})',
    re.IGNORECASE,
)


def _is_valid_title(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    if text.startswith(("#", "http://", "https://")):
        return False
    word_count = len(text.split())
    return 1 <= word_count <= 7


def _extract_director_near_title(text: str, match_end: int, match_start: int) -> str | None:
    """Try to find a director name near a quoted title."""
    # 1. After closing quote: «Title» Firstname Lastname
    after = text[match_end:match_end + 80].lstrip()
    for pat in (_CYR_FULLNAME, _LAT_FULLNAME):
        m = pat.match(after)
        if m:
            return m.group(1)

    # 2. Before quote with keyword: режиссёра Имя Фамилия ... «Title»
    #    or: Снявший «Title» Имя Фамилия
    before = text[max(0, match_start - 120):match_start]
    m = _DIRECTOR_KEYWORD.search(before)
    if m:
        return m.group(1)

    # 3. Keyword pattern after title: Снявший «Title» Имя Фамилия
    #    (keyword is right before the quote, name is right after)
    keyword_before = re.search(r'(?:режисс[её]р[аы]?|[Сс]нявш[а-я]*)\s*$', before, re.IGNORECASE)
    if keyword_before:
        for pat in (_CYR_FULLNAME, _LAT_FULLNAME):
            m = pat.match(after)
            if m:
                return m.group(1)

    return None


def _find_nearest_year(text: str, title_start: int, title_end: int) -> int | None:
    """Find a year mention closest to the title position."""
    best_year = None
    best_dist = float('inf')
    for m in _YEAR_PATTERN.finditer(text):
        yr = int(m.group(1))
        dist = min(abs(m.start() - title_end), abs(m.end() - title_start))
        if dist < best_dist:
            best_dist = dist
            best_year = yr
    return best_year


def extract_titles(message) -> list[TitleContext]:
    """Extract movie/series titles from a Telegram message with context."""
    contexts: list[TitleContext] = []
    text = message.raw_text or ""

    # 1. Quoted text
    for match in _QUOTE_PATTERN.finditer(text):
        candidate = match.group(1).strip()
        if _is_valid_title(candidate):
            year = _find_nearest_year(text, match.start(), match.end())
            director = _extract_director_near_title(text, match.end(), match.start())
            contexts.append(TitleContext(title=candidate, year=year, director=director))

    if contexts:
        return contexts

    # 2. Bold entities (no context extraction — positions are less reliable)
    if message.entities:
        for entity in message.entities:
            if isinstance(entity, MessageEntityBold):
                candidate = text[entity.offset : entity.offset + entity.length].strip()
                if _is_valid_title(candidate):
                    contexts.append(TitleContext(title=candidate))

    return contexts


async def extract_titles_smart(
    message, llm: LLMProvider | None = None,
) -> list[TitleContext]:
    """LLM-first extraction with regex fallback."""
    text = message.raw_text or ""
    if not text.strip():
        return []

    if llm is not None:
        try:
            items = await llm.extract_titles(text)
            if items:
                contexts = [
                    TitleContext(
                        title=item["title"],
                        year=item.get("year"),
                        director=item.get("director"),
                        is_english=True,
                    )
                    for item in items
                ]
                log.info("LLM extracted %d title(s): %s", len(contexts), contexts)
                return contexts
        except Exception:
            log.exception("LLM extraction failed, falling back to regex")

    return extract_titles(message)
