import json
import logging
import os
from typing import Protocol, runtime_checkable

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a movie/TV title extractor. Given a Telegram message (possibly in Russian) \
and/or one or more images (movie posters, film stills, or screenshots), \
extract all movie and TV series titles mentioned or visible.

Rules:
- Return titles in ENGLISH (translate from Russian if needed)
- Resolve Russian declensions to the correct title (e.g. "Крика" → "Scream")
- Include year and director ONLY if explicitly mentioned in the text
- Ignore hashtags, URLs, and channel names
- If you receive images, identify the movie/series from each one (poster text, visual cues)
- If no titles are found, return an empty list\
"""

# Defaults — overridden by env CHANNEL_MODELS / DM_MODELS (comma-separated)
_DEFAULT_CHANNEL_MODELS = "gemini-3-pro-preview"
_DEFAULT_DM_MODELS = "gemini-3-pro-preview"


def _parse_models(env_key: str, default: str) -> tuple[str, ...]:
    raw = os.environ.get(env_key, "").strip()
    models = [m.strip() for m in (raw or default).split(",") if m.strip()]
    return tuple(models)


CHANNEL_MODELS = _parse_models("CHANNEL_MODELS", _DEFAULT_CHANNEL_MODELS)
DM_MODELS = _parse_models("DM_MODELS", _DEFAULT_DM_MODELS)


class ExtractedTitle(BaseModel):
    title: str = Field(description="Movie or TV series title in English")
    year: int | None = Field(default=None, description="Year if mentioned")
    director: str | None = Field(default=None, description="Director if mentioned")


@runtime_checkable
class LLMProvider(Protocol):
    async def extract_titles(
        self, text: str, *, images: list[bytes] | None = None,
        source: str = "dm",
    ) -> list[dict]:
        """Return list of {"title": str, "year": int|None, "director": str|None}."""
        ...


class GeminiProvider:
    """Google GenAI SDK provider with smart model rotation.

    - Channel posts use best-quality models (gemini-3-pro → 2.5-pro → 2.5-flash)
    - DM requests round-robin across flash models to spread quota
    - On 429, automatically tries the next model in the chain
    """

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self._client = genai.Client(api_key=api_key)
        self._dm_index = 0  # round-robin counter for DM models

    async def _call(self, model: str, contents, config) -> str | None:
        response = await self._client.aio.models.generate_content(
            model=model, contents=contents, config=config,
        )
        return response.text

    def _get_model_chain(self, source: str) -> list[str]:
        """Return ordered model list based on source.

        For DM: start from current round-robin position, wrap around.
        For channel: fixed priority order.
        """
        if source == "channel":
            return list(CHANNEL_MODELS)

        # Round-robin: rotate starting position
        n = len(DM_MODELS)
        idx = self._dm_index % n
        chain = list(DM_MODELS[idx:]) + list(DM_MODELS[:idx])
        self._dm_index += 1
        return chain

    async def extract_titles(
        self, text: str, *, images: list[bytes] | None = None,
        source: str = "dm",
    ) -> list[dict]:
        parts: list = []
        if text:
            parts.append(types.Part.from_text(text=text))
        if images:
            for img in images:
                parts.append(types.Part.from_bytes(data=img, mime_type="image/jpeg"))

        contents = parts if parts else text
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,
            response_mime_type="application/json",
            response_schema=list[ExtractedTitle],
        )

        models = self._get_model_chain(source)
        last_error = None

        for model in models:
            try:
                response_text = await self._call(model, contents, config)
                if not response_text:
                    return []

                parsed = json.loads(response_text)
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

                log.info("Model: %s (%s)", model, source)
                return results

            except Exception as e:
                err_str = str(e)
                last_error = e
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "503" in err_str or "UNAVAILABLE" in err_str:
                    log.warning("Model %s unavailable, trying next: %s", model, e)
                    continue
                log.warning("Gemini extraction failed (%s): %s", model, e)
                return []

        log.warning("All %s models exhausted: %s", source, last_error)
        return []
