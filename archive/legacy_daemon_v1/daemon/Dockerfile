FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (needed for some Python packages)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code - maintain daemon/ structure
# This allows imports like "from daemon.queues.analysis_queue" to work
COPY . /app/daemon/

# Set working directory to daemon for running the app
WORKDIR /app/daemon

# Cloud Run sets PORT environment variable automatically (defaults to 8080)
# For local development, default to 8000
ENV HOST=0.0.0.0
ENV PORT=8080
ENV ALLOW_ALL_ORIGINS=true

# Expose port (Cloud Run uses 8080, but we'll read from PORT env var)
EXPOSE 8080

# Health check endpoint (Cloud Run has its own health checks, but this helps with Docker)
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Start the application
# PYTHONPATH is set so imports like "from daemon.queues" work
ENV PYTHONPATH=/app
CMD ["python", "start.py"]

