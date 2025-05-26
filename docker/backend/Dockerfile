ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE} AS base

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ARG CUDA_VERSION=12.1
ARG USE_GPU=false

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
RUN pip3 install --no-cache-dir pipenv && \
    pipenv install --deploy --system --dev

# Install PyTorch with CUDA support if using NVIDIA image
RUN if [ "${USE_GPU}" = "true" ]; then \
        # Extract CUDA version for PyTorch index URL  
        CUDA_SHORT=$(echo ${CUDA_VERSION} | sed 's/\.\([0-9]\)$/\1/'); \
        pip install torch --index-url https://download.pytorch.org/whl/cu${CUDA_SHORT}; \
    else \
        pip install torch --index-url https://download.pytorch.org/whl/cpu; \
    fi

# Create non-root user for running the application
RUN groupadd -r appuser && \
    useradd --no-log-init -r -g appuser -d /home/appuser appuser && \
    mkdir -p /home/appuser && \
    chown -R appuser:appuser /home/appuser

# Copy entrypoint script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod 755 /docker-entrypoint.sh

EXPOSE 5002

# Run the application through the entrypoint script
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "-u", "src/main.py"] 