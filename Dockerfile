# Bot Arena image: the `arena` command plus its dependencies.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1

WORKDIR /app
# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home arena && mkdir -p /app/data /app/charts && chown arena /app/data /app/charts
USER arena
# data/ holds the price cache and the KILL file; mount a volume there.
VOLUME ["/app/data"]
ENTRYPOINT ["arena"]
CMD ["--help"]
