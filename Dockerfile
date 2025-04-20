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
        gosu \
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

# Install PyTorch - CUDA version if using NVIDIA base, CPU version otherwise
RUN if echo ${BASE_IMAGE} | grep -q "nvidia"; then \
        pip install torch --index-url https://download.pytorch.org/whl/cu118; \
    else \
        pip install torch --index-url https://download.pytorch.org/whl/cpu; \
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

# Create required directories with proper permissions
RUN mkdir -p /app/config /app/in /app/processing /app/srv /app/src/instance && \
    touch /app/config/app.log && \
    chmod -R 777 /app/config /app/in /app/processing /app/srv /app/src/instance && \
    chmod 666 /app/config/app.log && \
    chown -R appuser:appuser /app

# Copy src directory for the entry point
COPY --chown=appuser:appuser src /app/src

# Ensure the app is fully accessible to the user
RUN chmod -R 777 /app

# Create entrypoint script to handle user permissions
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod 755 /docker-entrypoint.sh

# Run as root initially to allow user switching in entrypoint
USER root

EXPOSE 5001

# Run the application through the entrypoint script
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "-u", "src/main.py"] 