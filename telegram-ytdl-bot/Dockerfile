# Multi-stage build for optimized image
FROM python:3.10-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.10-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    aria2 \
    postgresql-client \
    redis-tools \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN useradd -m -u 1000 botuser

# Create necessary directories
RUN mkdir -p /app /tmp/ytdl_downloads && \
    chown -R botuser:botuser /app /tmp/ytdl_downloads

# Set working directory
WORKDIR /app

# Copy application files
COPY --chown=botuser:botuser . .

# Switch to non-root user
USER botuser

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DOWNLOAD_DIR=/tmp/ytdl_downloads

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import asyncio; from database.manager import db_manager; asyncio.run(db_manager.get_user_count())" || exit 1

# Run the bot
CMD ["python", "main.py"]