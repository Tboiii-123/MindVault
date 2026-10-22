import tempfile

from .base import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = "test-secret-key-that-is-long-enough-for-hmac-sha256-0123456789"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = False
MEDIA_ROOT = tempfile.mkdtemp(prefix="ainotes-test-media-")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
THROTTLE_OVERRIDE = True
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": dict.fromkeys(("user", "anon", "auth", "uploads", "ai", "public"), "10000/min"),
}
AI_STT_PROVIDER = "apps.ai.providers.fake.FakeSTTProvider"
AI_LLM_PROVIDER = "apps.ai.providers.fake.FakeLLMProvider"
WHITENOISE_AUTOREFRESH = True
STATIC_ROOT = tempfile.mkdtemp(prefix="ainotes-test-static-")
