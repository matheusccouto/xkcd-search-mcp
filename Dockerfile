FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

# Install external deps without the local package so the model download
# layer below is only invalidated by dependency changes, not source changes.
RUN uv sync --frozen --no-dev --no-install-project

RUN uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

COPY README.md LICENSE ./
COPY src/ ./src/

RUN uv sync --frozen --no-dev

ENV PORT=7860
EXPOSE 7860

CMD ["uv", "run", "python", "-m", "xkcd_search.server"]
