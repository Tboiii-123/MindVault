# syntax=docker/dockerfile:1.7

# ---------- base ----------
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# ---------- builder: compile wheels once ----------
FROM base AS builder
COPY requirements/ requirements/
RUN pip wheel --wheel-dir /wheels -r requirements/prod.txt

# ---------- app: dependencies + code (shared by dev and runtime) ----------
FROM base AS app
RUN addgroup --system app && adduser --system --ingroup app --home /app app \
    && apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /wheels /wheels
COPY requirements/ requirements/
RUN pip install --no-index --find-links=/wheels -r requirements/prod.txt && rm -rf /wheels
COPY --chown=app:app . .
# Windows checkouts may have CRLF line endings, which break shell scripts inside Linux containers
RUN sed -i 's/\r$//' scripts/*.sh && chmod +x scripts/*.sh \
    && mkdir -p /app/media /app/staticfiles && chown -R app:app /app/media /app/staticfiles
EXPOSE 8000
ENTRYPOINT ["/app/scripts/entrypoint.sh"]

# ---------- dev (used by docker-compose and CI): test/lint tools, auto-reload ----------
FROM app AS dev
RUN pip install -r requirements/dev.txt
USER app
ENV DJANGO_SETTINGS_MODULE=config.settings.dev
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# ---------- runtime (production image) ----------
FROM app AS runtime
# collectstatic only needs settings to import, not a real database or secret.
# django.setup() first, so any settings problem prints a full traceback.
RUN export DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY=build-only \
    && python -c "import django; django.setup(); print('settings OK')" \
    && python manage.py collectstatic --noinput
USER app
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
    CMD curl -fsS http://localhost:8000/health/live/ || exit 1
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "2", "--timeout", "60", "--access-logfile", "-"]