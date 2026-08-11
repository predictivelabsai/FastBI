FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt
COPY . .
ENV FASTBI_DB=/data/fastbi.sqlite
ENV FASTBI_PORT=5008
EXPOSE 5008
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:5008/healthz >/dev/null || exit 1
CMD ["sh", "-c", "python -c 'import db,seed; seed.build() if not db.db_exists() else None' && python web_app.py"]
