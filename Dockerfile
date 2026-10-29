FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN npm install -g pnpm@11.25.0 && pnpm install --frozen-lockfile
COPY frontend/ ./
COPY backend/app/ /backend/app/
COPY backend/requirements.lock /backend/requirements.lock
COPY data/ /data/
RUN pnpm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data STATIC_DIR=/app/static VAULT_KEY_FILE=/secrets/vault.key
WORKDIR /app
ARG APP_VERSION=dev
ARG APP_REVISION=unknown
ARG APP_BUILT_AT=
ARG APP_CHANNEL=custom
LABEL org.opencontainers.image.source="https://github.com/nikolasleeb/career-companion-local" org.opencontainers.image.version="$APP_VERSION" org.opencontainers.image.revision="$APP_REVISION"
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-liberation libreoffice-writer libreoffice-impress poppler-utils tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
ARG INSTALL_JOBSPY=false
RUN if [ "$INSTALL_JOBSPY" = "true" ]; then pip install --no-cache-dir python-jobspy==1.1.82; fi
RUN groupadd -g 10001 coach && useradd -u 10001 -g coach -m coach && mkdir /data /secrets && chown coach:coach /data /secrets
COPY backend/ ./
COPY data/ ./data/
RUN python -c "import json,os; from pathlib import Path; Path('app/build-info.json').write_text(json.dumps(dict(version=os.environ['APP_VERSION'],revision=os.environ['APP_REVISION'],built_at=os.environ['APP_BUILT_AT'],channel=os.environ['APP_CHANNEL'])))"

COPY --from=frontend /build/dist/ ./static/
USER coach
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=2)"
CMD ["python", "-m", "app.serve"]
