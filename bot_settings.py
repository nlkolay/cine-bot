from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

DEFAULTS = {
    "llm_enabled": True,
    "auto_post": True,
    "allowed_users": [],       # seeded from config.ALLOWED_USERS
    "source_channels": [],     # seeded from config.SOURCE_CHANNELS
}

_OCR_MODES = ("fallback", "always")


class Settings:
    def __init__(self, path: str):
        self._path = path
        self._data: dict = {}
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path) as f:
                    self._data = json.load(f)
                log.info("Loaded settings from %s", self._path)
            except Exception:
                log.exception("Failed to load settings, using defaults")
                self._data = {}

        for key, default in DEFAULTS.items():
            self._data.setdefault(key, default if not isinstance(default, list) else list(default))

    def _save(self):
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self._path)

    def get(self, key: str):
        return self._data.get(key, DEFAULTS.get(key))

    def set(self, key: str, val):
        self._data[key] = val
        self._save()

    def toggle(self, key: str) -> bool:
        self._data[key] = not self._data.get(key, False)
        self._save()
        return self._data[key]

    def cycle(self, key: str, values: tuple) -> str:
        cur = self._data.get(key, values[0])
        idx = (values.index(cur) + 1) % len(values) if cur in values else 0
        self._data[key] = values[idx]
        self._save()
        return self._data[key]

    def add_to_list(self, key: str, val) -> bool:
        lst = self._data.setdefault(key, [])
        if val in lst:
            return False
        lst.append(val)
        self._save()
        return True

    def remove_from_list(self, key: str, val) -> bool:
        lst = self._data.get(key, [])
        if val not in lst:
            return False
        lst.remove(val)
        self._save()
        return True

    def seed_defaults(self, allowed_users: set[int], source_channels: list[str]):
        """Seed lists from env vars on first run (only if lists are empty)."""
        if not self._data.get("allowed_users"):
            self._data["allowed_users"] = sorted(allowed_users)
        if not self._data.get("source_channels"):
            self._data["source_channels"] = list(source_channels)
        self._save()
