# Grant Data Quality & Reporting Assistant — Streamlit app image.
#
#   docker build -t grant-assistant .
#   docker run -p 8501:8501 grant-assistant
#
# Pass an API key to enable AI features (optional):
#   docker run -p 8501:8501 -e ANTHROPIC_API_KEY=sk-ant-... grant-assistant

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Install dependencies first for layer caching.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

COPY configs ./configs
COPY sample_data ./sample_data
COPY .streamlit ./.streamlit

EXPOSE 8501
ENV PYTHONUNBUFFERED=1

HEALTHCHECK CMD uv run python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["uv", "run", "streamlit", "run", "src/grant_assistant/ui/app.py", \
     "--server.port", "8501", "--server.address", "0.0.0.0", "--server.headless", "true"]
