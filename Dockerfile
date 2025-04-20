ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE} AS base

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies based on base image
RUN if [ -f /etc/debian_version ]; then \
        apt-get update && \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ffmpeg \
        build-essential \
        && apt-get clean && \
        rm -rf /var/lib/apt/lists/* ; \
    fi

# Set up Python environment
COPY Pipfile Pipfile.lock ./

# Install pipenv and dependencies
RUN if [ $(command -v pip3) ]; then \
        pip3 install --no-cache-dir pipenv && \
        pipenv install --deploy --system --dev; \
    else \
        pip install --no-cache-dir pipenv && \
        pipenv install --deploy --system --dev; \
    fi

# Install CUDA-enabled PyTorch if using NVIDIA base
RUN if echo ${BASE_IMAGE} | grep -q "nvidia"; then \
        pip install torch --index-url https://download.pytorch.org/whl/cu118; \
    fi

# Create non-root user
RUN if getent group appuser > /dev/null 2>&1; then \
        echo "Group exists"; \
    else \
        groupadd -r appuser; \
    fi && \
    if id appuser > /dev/null 2>&1; then \
        echo "User exists"; \
    else \
        useradd --no-log-init -r -g appuser -d /home/appuser appuser; \
    fi && \
    mkdir -p /home/appuser && \
    chown -R appuser:appuser /home/appuser

# Copy application code
COPY --chown=appuser:appuser . /app
RUN mkdir -p /app/config /app/in /app/processing /app/srv /app/src/instance && \
    touch /app/config/app.log && \
    chmod 666 /app/config/app.log && \
    chown -R appuser:appuser /app

USER appuser
ENV HOME=/home/appuser

EXPOSE 5001

# Run the application
CMD ["python", "-u", "src/main.py"] 