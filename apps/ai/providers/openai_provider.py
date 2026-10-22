"""OpenAI-backed STT (Whisper) and LLM (chat completions, JSON mode)."""

from __future__ import annotations

import json
import logging

from django.conf import settings

from .base import (
    EntryAnalysis,
    LLMProvider,
    PermanentAIError,
    STTProvider,
    TitleSuggestion,
    Transcript,
    TransientAIError,
)

logger = logging.getLogger(__name__)


def _client():
    import openai  # lazy: not needed when using the fake provider

    return openai.OpenAI(api_key=settings.OPENAI_API_KEY, timeout=120, max_retries=0)


def _translate_errors(fn):
    def wrapper(*a, **kw):
        import openai

        try:
            return fn(*a, **kw)
        except (
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.InternalServerError,
        ) as e:
            raise TransientAIError(str(e)) from e
        except openai.APIStatusError as e:
            raise PermanentAIError(f"{e.status_code}: {e}") from e

    return wrapper


class OpenAISTTProvider(STTProvider):
    @_translate_errors
    def transcribe(self, file, *, filename: str, mime: str = "") -> Transcript:
        resp = _client().audio.transcriptions.create(
            model=settings.OPENAI_STT_MODEL,
            file=(filename, file, mime or "application/octet-stream"),
            response_format="verbose_json",
        )
        return Transcript(
            text=(resp.text or "").strip(),
            language=getattr(resp, "language", "") or "",
            duration_seconds=getattr(resp, "duration", None),
        )


class OpenAILLMProvider(LLMProvider):
    def _json(self, system: str, user: str) -> dict:
        resp = _client().chat.completions.create(
            model=settings.OPENAI_LLM_MODEL,
            response_format={"type": "json_object"},
            temperature=0.2,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        try:
            return json.loads(resp.choices[0].message.content or "{}")
        except json.JSONDecodeError as e:
            raise TransientAIError("LLM returned invalid JSON") from e

    @_translate_errors
    def analyze_entry(self, text: str) -> EntryAnalysis:
        data = self._json(
            "You analyse a personal note. Reply ONLY with JSON: "
            '{"summary": str (<=2 sentences), "key_points": [str], "action_items": [str], "tags": [str] (<=5, lowercase)}. '
            "Use only information in the note.",
            text[:20000],
        )
        return EntryAnalysis(
            summary=str(data.get("summary", ""))[:1000],
            key_points=[str(x) for x in data.get("key_points", [])][:10],
            action_items=[str(x) for x in data.get("action_items", [])][:10],
            tags=[str(x).lower()[:40] for x in data.get("tags", [])][:5],
        )

    @_translate_errors
    def suggest_title(self, text: str) -> TitleSuggestion:
        data = self._json(
            'Name the topic of this note. Reply ONLY with JSON: {"title": str (2-5 words), "icon": one emoji}.',
            text[:4000],
        )
        return TitleSuggestion(title=str(data.get("title", "Untitled"))[:200], icon=str(data.get("icon", ""))[:16])

    @_translate_errors
    def summarize_container(self, title: str, notes: list[str]) -> str:
        data = self._json(
            "Summarise these notes grouped under topic headings with key points and action items. "
            'Reply ONLY with JSON: {"summary": str (markdown)}. Use only the provided notes.',
            f"Topic: {title}\n\n" + "\n---\n".join(notes),
        )
        return str(data.get("summary", ""))
