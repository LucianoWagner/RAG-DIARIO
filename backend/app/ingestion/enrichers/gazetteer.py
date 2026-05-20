"""
Gazetteer helpers for Argentina-related locations and institutions.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import get_settings


@dataclass
class Gazetteer:
    city: str
    aliases: list[str]
    institutions: list[str]
    keywords: list[str]
    direct_argentina_sections: list[str]

    def find_locations(self, text: str) -> list[str]:
        normalized_text = _strip_accents(text).lower()
        found: list[str] = []
        for alias in self.aliases:
            normalized_alias = _strip_accents(alias).lower().strip()
            if normalized_alias and _contains_term(normalized_text, normalized_alias) and alias not in found:
                found.append(alias)
        return found

    def pick_primary_location(self, locations: list[str]) -> str | None:
        if self.city in locations:
            return self.city
        return locations[0] if locations else None


@lru_cache()
def load_gazetteer() -> Gazetteer:
    settings = get_settings()
    gazetteer_path = Path(settings.gazetteer_path)
    if not gazetteer_path.is_absolute():
        gazetteer_path = Path(__file__).resolve().parents[4] / gazetteer_path
    data = json.loads(gazetteer_path.read_text(encoding="utf-8"))
    aliases = [data.get("country") or data["city"]]
    aliases.append(data["city"])
    aliases.extend(data.get("provinces", []))
    aliases.extend(data.get("cities", []))
    aliases.extend(data.get("neighborhoods", []))
    aliases.extend(data.get("nearby_partidos", []))
    aliases.extend(data.get("landmarks", []))
    institutions = []
    institutions.extend(data.get("institutions", []))
    institutions.extend(data.get("political_organizations", []))
    institutions.extend(data.get("clubs", []))
    return Gazetteer(
        city=data["city"],
        aliases=aliases,
        institutions=institutions,
        keywords=data.get("keywords", []),
        direct_argentina_sections=data.get("direct_argentina_sections", []),
    )


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _contains_term(normalized_text: str, normalized_term: str) -> bool:
    pattern = rf"(?<!\w){re.escape(normalized_term)}(?!\w)"
    return re.search(pattern, normalized_text, flags=re.IGNORECASE) is not None
