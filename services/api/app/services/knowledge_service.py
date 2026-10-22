from __future__ import annotations

import json
import os
import re
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "knowledge_base.json"
KNOWLEDGE_PATH = Path(os.getenv("G1_KNOWLEDGE_PATH", str(DEFAULT_PATH)))


def retrieve_knowledge(question: str, limit: int = 3) -> list[dict[str, str]]:
    """Read editable knowledge from disk and return keyword-matched entries."""
    try:
        data = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise RuntimeError(f"Cannot read G1 knowledge base: {exc}") from exc
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        raise RuntimeError("Knowledge base 'entries' must be a list")
    words = set(re.findall(r"\w+", question.casefold()))
    ranked: list[tuple[int, dict[str, str]]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        title, facts = item.get("title"), item.get("facts")
        if not isinstance(title, str) or not isinstance(facts, str):
            continue
        keywords = item.get("keywords", [])
        if not isinstance(keywords, list):
            continue
        score = sum(2 for keyword in keywords if isinstance(keyword, str) and keyword.casefold() in words)
        score += sum(1 for word in re.findall(r"\w+", title.casefold()) if word in words)
        if score:
            ranked.append((score, {"title": title, "facts": facts}))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in ranked[:limit]]


def format_knowledge(entries: list[dict[str, str]]) -> str:
    if not entries:
        return "No relevant verified laboratory knowledge was found. Do not invent local facts."
    return "\n\n".join(f"Topic: {entry['title']}\nFacts: {entry['facts']}" for entry in entries)