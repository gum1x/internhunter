FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code@latest || true

COPY pyproject.toml ./
COPY internhunter ./internhunter
COPY migrations ./migrations

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN mkdir -p /data

EXPOSE 8000

ENTRYPOINT ["internhunter"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
