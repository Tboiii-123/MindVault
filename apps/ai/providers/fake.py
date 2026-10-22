"""Deterministic offline providers for local dev, tests and CI (no API keys, no cost)."""

from __future__ import annotations

import re

from .base import (
    EntryAnalysis,
    LLMProvider,
    STTProvider,
    TitleSuggestion,
    Transcript,
)

_STOP = set(
    "the a an and or but if then to of in on for with is are was were be been it this that i we you "
    "my our your at as by from so do does did have has had not no can could should would will just "
    "about into than also very more most some any".split()
)


def _keywords(text: str, n: int = 5) -> list[str]:
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z\-]{3,}", text.lower()) if w not in _STOP]
    seen: dict[str, int] = {}
    for w in words:
        seen[w] = seen.get(w, 0) + 1
    return [w for w, _ in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


class FakeSTTProvider(STTProvider):
    def transcribe(self, file, *, filename: str, mime: str = "") -> Transcript:
        data = file.read()
        if data.startswith(b"TRANSCRIPT:"):  # tests can embed the "spoken" text in the file
            text = data[len(b"TRANSCRIPT:") :].decode("utf-8", "ignore").strip()
        else:
            text = f"Simulated transcript of {filename} ({len(data)} bytes)."
        return Transcript(text=text, language="en", duration_seconds=max(1.0, len(data) / 16000))


class FakeLLMProvider(LLMProvider):
    def analyze_entry(self, text: str) -> EntryAnalysis:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        actions = [s for s in sentences if re.match(r"(?i)^(todo|need to|must|should|remember to)\b", s)]
        return EntryAnalysis(
            summary=" ".join(sentences[:2])[:300],
            key_points=sentences[:3],
            action_items=actions,
            tags=_keywords(text),
        )

    def suggest_title(self, text: str) -> TitleSuggestion:
        kws = _keywords(text, 3)
        return TitleSuggestion(title=" ".join(w.capitalize() for w in kws) or "Untitled", icon="📝")

    def summarize_container(self, title: str, notes: list[str]) -> str:
        bullets = "\n".join(f"- {n[:120]}" for n in notes[:10])
        return f"Summary of {title} ({len(notes)} notes):\n{bullets}"
