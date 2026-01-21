# Multi-stage Dockerfile for LeadForge
# Stage 1: Build frontend assets
FROM node:18-alpine AS frontend-builder

WORKDIR /app/dashboards/client
COPY dashboards/client/package*.json ./
# Install all dependencies (including dev) for build
RUN npm ci

COPY dashboards/client ./
RUN npm run build

# Stage 2: Python dependencies
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy AS python-builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 3: Production runtime
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r leadforge && useradd -r -g leadforge leadforge

# Copy Python packages from builder
COPY --from=python-builder /root/.local /home/leadforge/.local
ENV PATH=/home/leadforge/.local/bin:$PATH

# Copy application code
COPY --chown=leadforge:leadforge . .

# Copy built frontend from frontend-builder
COPY --from=frontend-builder --chown=leadforge:leadforge /app/dashboards/client/dist ./dashboards/client/dist

# Create necessary directories with correct permissions
RUN mkdir -p \
    /app/data \
    /app/logs \
    /app/runtime \
    /app/slots \
    /app/browser_profiles && \
    chown -R leadforge:leadforge /app

# Copy entrypoint script
COPY --chown=leadforge:leadforge scripts/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Switch to non-root user
USER leadforge

# Expose API port
EXPOSE 8001

# Set environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    NODE_ENV=production

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["api"]
