"""
Gazetteer helpers for La Plata locations.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import get_settings


@dataclass
class Gazetteer:
    city: str
    aliases: list[str]

    def find_locations(self, text: str) -> list[str]:
        lowered = text.lower()
        found: list[str] = []
        for alias in self.aliases:
            if alias.lower() in lowered and alias not in found:
                found.append(alias)
        return found

    def pick_primary_location(self, locations: list[str]) -> str | None:
        if self.city in locations:
            return self.city
        return locations[0] if locations else None


@lru_cache()
def load_gazetteer() -> Gazetteer:
    settings = get_settings()
    data = json.loads(Path(settings.gazetteer_path).read_text(encoding="utf-8"))
    aliases = [data["city"]]
    aliases.extend(data.get("neighborhoods", []))
    aliases.extend(data.get("nearby_partidos", []))
    aliases.extend(data.get("landmarks", []))
    return Gazetteer(city=data["city"], aliases=aliases)
