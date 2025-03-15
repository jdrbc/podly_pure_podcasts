FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04

# Prevents Python from writing pyc files.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get upgrade -y &&\
  apt-get install -y python3 python3-pip nano ffmpeg

COPY Pipfile Pipfile.lock ./
RUN python3 -m pip install --upgrade pip
RUN pip install pipenv && pipenv install --dev --system --deploy
RUN pip install torch

# Copy the source code into the container.
COPY . /app

# Creates a non-root user and adds permission to access the /app folder
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

# Expose the port that the application listens on.
EXPOSE 5001

# Run the application.
CMD python3 src/main.py
