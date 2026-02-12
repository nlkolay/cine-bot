import logging
from typing import Protocol, runtime_checkable

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a movie/TV title extractor. Given a Telegram message (possibly in Russian), \
extract all movie and TV series titles mentioned.

Rules:
- Return titles in ENGLISH (translate from Russian if needed)
- Resolve Russian declensions to the correct title (e.g. "Крика" → "Scream")
- Include year and director ONLY if explicitly mentioned in the text
- Ignore hashtags, URLs, and channel names
- If no titles are found, return an empty list\
"""


class ExtractedTitle(BaseModel):
    title: str = Field(description="Movie or TV series title in English")
    year: int | None = Field(default=None, description="Year if mentioned")
    director: str | None = Field(default=None, description="Director if mentioned")


@runtime_checkable
class LLMProvider(Protocol):
    async def extract_titles(self, text: str) -> list[dict]:
        """Return list of {"title": str, "year": int|None, "director": str|None}."""
        ...


class GeminiProvider:
    """Google GenAI SDK provider for title extraction."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self._model = model
        self._client = genai.Client(api_key=api_key)

    async def extract_titles(self, text: str) -> list[dict]:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=text,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=list[ExtractedTitle],
                ),
            )

            if not response.text:
                return []

            import json
            parsed = json.loads(response.text)
            if not isinstance(parsed, list):
                return []

            results = []
            for item in parsed:
                if not isinstance(item, dict) or "title" not in item:
                    continue
                results.append({
                    "title": str(item["title"]),
                    "year": int(item["year"]) if item.get("year") else None,
                    "director": str(item["director"]) if item.get("director") else None,
                })
            return results

        except Exception as e:
            log.warning("Gemini extraction failed: %s", e)
            return []
