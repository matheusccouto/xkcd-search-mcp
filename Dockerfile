FROM python:3.12-slim

ARG EMBED_MODEL=BAAI/bge-small-en-v1.5  # Keep in sync with builder.py EMBED_MODEL_NAME

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project

RUN uv run --no-project python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('$EMBED_MODEL')"

COPY README.md LICENSE ./
COPY src/ ./src/

RUN uv sync --frozen --no-dev

ENV PORT=7860
EXPOSE 7860

CMD ["uv", "run", "python", "-m", "xkcd_search.server"]
