# Build stage
FROM python:3.13.7-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --target=/app/dependencies -r requirements.txt

# Production stage
FROM python:3.13.7-slim

WORKDIR /app

# Copy dependencies from builder
COPY --from=builder /app/dependencies /app/dependencies

# Add dependencies to Python path
ENV PYTHONPATH=/app/dependencies:/app

# Copy application code
COPY src/ /app/src/

# Copy entry point script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

# Create non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Default command (can be overridden)
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["--help"]
