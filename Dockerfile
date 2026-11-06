FROM python:3.12-slim

ARG APP_UID=1000
ARG APP_GID=1000

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir . \
    && groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" \
       --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/data \
    && chown "${APP_UID}:${APP_GID}" /app/data

COPY static ./static

USER app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "100", "--timeout-keep-alive", "5"]
