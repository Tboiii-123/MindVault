from functools import lru_cache

from django.conf import settings
from django.utils.module_loading import import_string

from .providers.base import LLMProvider, STTProvider


@lru_cache(maxsize=1)
def get_stt() -> STTProvider:
    return import_string(settings.AI_STT_PROVIDER)()


@lru_cache(maxsize=1)
def get_llm() -> LLMProvider:
    return import_string(settings.AI_LLM_PROVIDER)()
