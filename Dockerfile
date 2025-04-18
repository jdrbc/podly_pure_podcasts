FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get update --allow-insecure-repositories && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends --allow-unauthenticated \
    ffmpeg \
    build-essential \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY Pipfile Pipfile.lock ./

RUN pip install --no-cache-dir pipenv && \
    pipenv install --deploy --system --dev

RUN groupadd -r appuser && \
    useradd --no-log-init -r -g appuser -d /home/appuser appuser && \
    mkdir -p /home/appuser && \
    chown -R appuser:appuser /home/appuser

FROM base AS final

COPY --chown=appuser:appuser . /app
RUN mkdir -p /app/config /app/in /app/processing /app/srv /app/src/instance && \
    touch /app/config/app.log && \
    chmod 666 /app/config/app.log && \
    chown -R appuser:appuser /app

USER appuser

ENV HOME=/home/appuser

EXPOSE 5001

CMD ["python", "-u", "src/main.py"]
