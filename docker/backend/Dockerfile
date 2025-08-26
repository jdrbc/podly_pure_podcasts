ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE} AS base

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ARG CUDA_VERSION=12.4.1
ARG ROCM_VERSION=6.4
ARG USE_GPU=false
ARG USE_GPU_NVIDIA=${USE_GPU}
ARG USE_GPU_AMD=false

WORKDIR /app

# Install dependencies based on base image
RUN if [ -f /etc/debian_version ]; then \
        apt-get update && \
        apt-get install ca-certificates && \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ffmpeg \
        build-essential \
        gosu \
        python3-pip \
        python3 \
        && if [ $(python3 --version | awk '{print $2}' | cut -d '.' -f2) -lt 11 ]; then apt-get install -y python3-tomli; fi \
        && apt-get clean && \
        rm -rf /var/lib/apt/lists/* ; \
    fi

# Set up Python environment
COPY Pipfile Pipfile.lock ./

# Install pipenv and dependencies
RUN pip3 install --no-cache-dir pipenv && \
    pipenv install --deploy --system --dev

# Install PyTorch with CUDA support if using NVIDIA image
RUN if [ "${USE_GPU}" = "true" ] || [ "${USE_GPU_NVIDIA}" = "true" ]; then \
        pip install nvidia-cudnn-cu12; \
        pip install torch; \
    elif [ "${USE_GPU_AMD}" = "true" ]; then \
        pip install torch --index-url https://download.pytorch.org/whl/rocm${ROCM_VERSION}; \
    else \
        pip install torch --index-url https://download.pytorch.org/whl/cpu; \
    fi

# Copy application code
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY config/config.yml.example ./config/
COPY config/system_prompt.txt ./config/
COPY config/user_prompt.jinja ./config/

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

EXPOSE 5002

# Run the application through the entrypoint script
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python3", "-u", "src/main.py"]

