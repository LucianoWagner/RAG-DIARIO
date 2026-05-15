"""
spaCy-based NER with lazy loading.
"""

from functools import lru_cache

import spacy

_PERSON_LABELS = {"PER", "PERSON"}
_ORG_LABELS = {"ORG"}


@lru_cache()
def _load_model():
    return spacy.load("es_core_news_md")


def extract_entities(text: str) -> dict[str, list[str]]:
    doc = _load_model()(text)
    persons: list[str] = []
    organizations: list[str] = []
    seen_persons: set[str] = set()
    seen_orgs: set[str] = set()

    for ent in doc.ents:
        value = ent.text.strip()
        if ent.label_ in _PERSON_LABELS and value not in seen_persons:
            seen_persons.add(value)
            persons.append(value)
        elif ent.label_ in _ORG_LABELS and value not in seen_orgs:
            seen_orgs.add(value)
            organizations.append(value)

    return {"persons": persons, "organizations": organizations}
