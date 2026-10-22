"""Base settings shared by every environment. Everything configurable comes from env vars."""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# --------------------------------------------------------------------------- apps
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # Third Party Apps
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",
    "storages",
    # Local Apps
    "apps.common",
    "apps.users",
    "apps.containers",
    "apps.ai",
    "apps.sharing",
    "apps.search",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------- database
DATABASES = {"default": env.db("DATABASE_URL", default="postgres://postgres:yinkus@localhost:5432/ainotes")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------- cache / redis
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "ainotes",
    }
}

# --------------------------------------------------------------------------- auth
AUTH_USER_MODEL = "users.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:3000")

# --------------------------------------------------------------------------- DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "user": env("THROTTLE_USER", default="600/min"),
        "anon": env("THROTTLE_ANON", default="60/min"),
        "auth": env("THROTTLE_AUTH", default="10/min"),
        "uploads": env("THROTTLE_UPLOADS", default="30/min"),
        "ai": env("THROTTLE_AI", default="20/min"),
        "public": env("THROTTLE_PUBLIC", default="120/min"),
    },
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "AI Personal Notes API",
    "DESCRIPTION": "Self-chat style notes with voice, AI processing, search and sharing.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --------------------------------------------------------------------------- i18n / static
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Audio goes to S3-compatible storage (AWS S3, MinIO, R2...) when USE_S3=1, else local disk.
USE_S3 = env.bool("USE_S3", default=False)
if USE_S3:
    AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default=None)
    AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default=None)
    AWS_S3_ADDRESSING_STYLE = env("AWS_S3_ADDRESSING_STYLE", default="path")
    AWS_QUERYSTRING_AUTH = True  # pre-signed, expiring URLs: bucket stays private
    AWS_QUERYSTRING_EXPIRE = env.int("AUDIO_URL_TTL_SECONDS", default=3600)
    AWS_DEFAULT_ACL = None
    AWS_S3_FILE_OVERWRITE = False
    default_storage = {"BACKEND": "storages.backends.s3.S3Storage"}
else:
    default_storage = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

STORAGES = {
    "default": default_storage,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --------------------------------------------------------------------------- uploads
AUDIO_MAX_BYTES = env.int("AUDIO_MAX_BYTES", default=25 * 1024 * 1024)
AUDIO_ALLOWED_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/mp4", "audio/x-m4a", "audio/m4a", "audio/wav",
    "audio/x-wav", "audio/webm", "audio/ogg", "audio/aac", "audio/flac", "video/webm",
}  # fmt: skip
AUDIO_ALLOWED_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".wav", ".webm", ".ogg", ".aac", ".flac", ".oga"}
DATA_UPLOAD_MAX_MEMORY_SIZE = AUDIO_MAX_BYTES + 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # larger uploads stream to temp files

# --------------------------------------------------------------------------- celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_ACKS_LATE = True  # re-deliver if a worker dies mid-task
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # fair dispatch for long STT jobs
CELERY_TASK_SOFT_TIME_LIMIT = 600
CELERY_TASK_TIME_LIMIT = 660
CELERY_RESULT_EXPIRES = 3600
CELERY_TASK_IGNORE_RESULT = True  # state lives in Postgres, not in the result backend
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {
    "ai.transcribe_and_process_entry": {"queue": "ai"},
    "ai.summarize_container": {"queue": "ai"},
}
CELERY_BEAT_SCHEDULE = {
    "requeue-stuck-entries": {
        "task": "ai.requeue_stuck_entries",
        "schedule": 300.0,
    },
}

# --------------------------------------------------------------------------- AI
AI_STT_PROVIDER = env("AI_STT_PROVIDER", default="apps.ai.providers.fake.FakeSTTProvider")
AI_LLM_PROVIDER = env("AI_LLM_PROVIDER", default="apps.ai.providers.fake.FakeLLMProvider")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
OPENAI_STT_MODEL = env("OPENAI_STT_MODEL", default="whisper-1")
OPENAI_LLM_MODEL = env("OPENAI_LLM_MODEL", default="gpt-4o-mini")
AI_MIN_CHARS_FOR_ANALYSIS = env.int("AI_MIN_CHARS_FOR_ANALYSIS", default=80)
AI_CONTAINER_SUMMARY_CHAR_BUDGET = env.int("AI_CONTAINER_SUMMARY_CHAR_BUDGET", default=24000)
AI_STUCK_ENTRY_MINUTES = env.int("AI_STUCK_ENTRY_MINUTES", default=15)
SEARCH_CONFIG = env("SEARCH_CONFIG", default="english")

# --------------------------------------------------------------------------- sharing
PUBLIC_SHARE_CACHE_SECONDS = env.int("PUBLIC_SHARE_CACHE_SECONDS", default=60)

# --------------------------------------------------------------------------- email
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="AI Notes <no-reply@example.com>")

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"])

# --------------------------------------------------------------------------- logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "default"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
