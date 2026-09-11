FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Use the same hash-verified runtime dependencies as the documented pip install.
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements-lock.txt

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .

COPY login_setup.py ./

# Session credentials live in this user's home and can be persisted with a volume.
RUN useradd --create-home --uid 10001 app \
    && mkdir /home/app/.monarch-mcp-server \
    && chown app:app /home/app/.monarch-mcp-server
USER app

CMD ["monarch-mcp-server"]
