"""Provider interfaces. Swap OpenAI / Deepgram / local Whisper / Anthropic by changing one env var."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class TransientAIError(Exception):
    """Timeouts, rate limits, 5xx: Celery retries these with exponential backoff."""


class PermanentAIError(Exception):
    """Bad audio, content refused, etc.: retrying will not help."""


@dataclass
class Transcript:
    text: str
    language: str = ""
    duration_seconds: float | None = None


@dataclass
class EntryAnalysis:
    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class TitleSuggestion:
    title: str
    icon: str = ""


class STTProvider(ABC):
    @abstractmethod
    def transcribe(self, file, *, filename: str, mime: str = "") -> Transcript: ...


class LLMProvider(ABC):
    @abstractmethod
    def analyze_entry(self, text: str) -> EntryAnalysis: ...

    @abstractmethod
    def suggest_title(self, text: str) -> TitleSuggestion: ...

    @abstractmethod
    def summarize_container(self, title: str, notes: list[str]) -> str: ...
