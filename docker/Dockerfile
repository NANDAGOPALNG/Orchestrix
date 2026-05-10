# Use a slim Python image that satisfies pyproject.toml (>=3.12)
FROM python:3.12-slim-bookworm

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Use the Python already installed in this image. This prevents uv from
# downloading a standalone Python during Docker builds.
ENV UV_PYTHON_DOWNLOADS=never

# Set working directory
WORKDIR /app

# Copy dependency files first (for caching)
COPY pyproject.toml uv.lock .python-version ./

# Install dependencies (no-install-project skips installing the app itself here)
RUN uv sync --frozen --no-install-project --no-dev --python /usr/local/bin/python

# Copy the rest of the application
COPY . .

# Place /app/.venv/bin at the beginning of PATH
ENV PATH="/app/.venv/bin:$PATH"

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
