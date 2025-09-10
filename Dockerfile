# Multi-stage build for combined frontend and backend
ARG BASE_IMAGE=python:3.11-slim
FROM node:18-alpine AS frontend-build

WORKDIR /app

# Copy frontend package files
COPY frontend/package*.json ./
RUN npm ci

# Copy frontend source code
COPY frontend/ ./

# Build frontend assets
RUN npm run build

# Backend stage
FROM ${BASE_IMAGE} AS backend

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ARG CUDA_VERSION=12.4.1
ARG ROCM_VERSION=6.4
ARG USE_GPU=false
ARG USE_GPU_NVIDIA=${USE_GPU}
ARG USE_GPU_AMD=false
ARG LITE_BUILD=false

WORKDIR /app

# Install dependencies based on base image
RUN if [ -f /etc/debian_version ]; then \
    apt-get update && \
    apt-get install -y ca-certificates && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    gosu \
    python3 \
    python3-pip \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* ; \
    fi

# Install python3-tomli if Python version is less than 3.11 (separate step for ARM compatibility)
RUN if [ -f /etc/debian_version ]; then \
    PYTHON_MINOR=$(python3 --version 2>&1 | grep -o 'Python 3\.[0-9]*' | cut -d '.' -f2) && \
    if [ "$PYTHON_MINOR" -lt 11 ]; then \
    apt-get update && \
    apt-get install -y python3-tomli && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* ; \
    fi ; \
    fi

# Set up Python environment
COPY Pipfile Pipfile.lock ./
COPY Pipfile.lite ./

# Install pipenv and dependencies
RUN if command -v pip >/dev/null 2>&1; then \
    pip install --no-cache-dir pipenv; \
    elif command -v pip3 >/dev/null 2>&1; then \
    pip3 install --no-cache-dir pipenv; \
    else \
    python3 -m pip install --no-cache-dir pipenv; \
    fi

# Set pip timeout and retries for better reliability
ENV PIP_DEFAULT_TIMEOUT=1000
ENV PIP_RETRIES=3
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_CACHE_DIR=1

# Install dependencies conditionally based on LITE_BUILD
RUN set -e && \
    if [ "${LITE_BUILD}" = "true" ]; then \
        echo "Installing lite dependencies (without Whisper)"; \
        cp Pipfile.lite Pipfile && \
        echo "Using lite Pipfile:" && \
        head -20 Pipfile && \
        PIPENV_VENV_IN_PROJECT=1 pipenv install --system --dev --verbose; \
    else \
        echo "Installing full dependencies (including Whisper)"; \
        echo "Using full Pipfile:" && \
        head -20 Pipfile && \
        PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy --system --dev --verbose; \
    fi

# Install PyTorch with CUDA support if using NVIDIA image (skip if LITE_BUILD)
RUN if [ "${LITE_BUILD}" = "true" ]; then \
    echo "Skipping PyTorch installation in lite mode"; \
    elif [ "${USE_GPU}" = "true" ] || [ "${USE_GPU_NVIDIA}" = "true" ]; then \
    if command -v pip >/dev/null 2>&1; then \
    pip install --no-cache-dir nvidia-cudnn-cu12 torch; \
    elif command -v pip3 >/dev/null 2>&1; then \
    pip3 install --no-cache-dir nvidia-cudnn-cu12 torch; \
    else \
    python3 -m pip install --no-cache-dir nvidia-cudnn-cu12 torch; \
    fi; \
    elif [ "${USE_GPU_AMD}" = "true" ]; then \
    if command -v pip >/dev/null 2>&1; then \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/rocm${ROCM_VERSION}; \
    elif command -v pip3 >/dev/null 2>&1; then \
    pip3 install --no-cache-dir torch --index-url https://download.pytorch.org/whl/rocm${ROCM_VERSION}; \
    else \
    python3 -m pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/rocm${ROCM_VERSION}; \
    fi; \
    else \
    if command -v pip >/dev/null 2>&1; then \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu; \
    elif command -v pip3 >/dev/null 2>&1; then \
    pip3 install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu; \
    else \
    python3 -m pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu; \
    fi; \
    fi

# Copy application code
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY config/config.yml.example ./config/
COPY config/system_prompt.txt ./config/
COPY config/user_prompt.jinja ./config/

# Copy built frontend assets to Flask static folder
COPY --from=frontend-build /app/dist ./src/app/static

# Create non-root user for running the application
RUN groupadd -r appuser && \
    useradd --no-log-init -r -g appuser -d /home/appuser appuser && \
    mkdir -p /home/appuser && \
    chown -R appuser:appuser /home/appuser

# Create necessary directories and set permissions
RUN mkdir -p /app/in /app/srv /app/processing /app/src/instance && \
    chown -R appuser:appuser /app

# Copy entrypoint script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod 755 /docker-entrypoint.sh

EXPOSE 5001

# Run the application through the entrypoint script
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python3", "-u", "src/main.py"]
