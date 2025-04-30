#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Checking for Docker...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker not found. Please install Docker first.${NC}"
    exit 1
fi

echo -e "${YELLOW}Checking for Docker Compose...${NC}"
if ! docker compose version &> /dev/null; then
    echo -e "${RED}Docker Compose not found. Please install Docker Compose first.${NC}"
    exit 1
fi

# Default values
BUILD_ONLY=false
TEST_BUILD=false
USE_GPU=false

# Check if NVIDIA GPU is available
if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null; then
    NVIDIA_GPU_AVAILABLE=true
else
    NVIDIA_GPU_AVAILABLE=false
fi

# Parse command line arguments
for arg in "$@"; do
    case $arg in
        --build)
            BUILD_ONLY=true
            shift
            ;;
        --test-build)
            TEST_BUILD=true
            shift
            ;;
        --gpu)
            USE_GPU=true
            shift
            ;;
        --cpu)
            USE_GPU=false
            shift
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--build] [--test-build] [--gpu] [--cpu]"
            exit 1
            ;;
    esac
done

# Determine if GPU should be used
if [ "$USE_GPU" = false ] && [ "$NVIDIA_GPU_AVAILABLE" = true ] && [ "$TEST_BUILD" = false ]; then
    echo "NVIDIA GPU detected. To force CPU usage, use --cpu flag."
    USE_GPU=true
fi

# Set base image and build arguments
if [ "$USE_GPU" = true ]; then
    echo "Building with NVIDIA GPU support..."
    BASE_IMAGE="nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04"
    DOCKER_RUNTIME="--runtime=nvidia"
else
    echo "Building without GPU support..."
    BASE_IMAGE="python:3.11-slim"
    DOCKER_RUNTIME=""
fi

# Build the Docker image
docker build --build-arg BASE_IMAGE="$BASE_IMAGE" -t podly-app -f Dockerfile .

# If only building, exit here
if [ "$BUILD_ONLY" = true ] || [ "$TEST_BUILD" = true ]; then
    echo "Build completed successfully."
    exit 0
fi

# Run the container
echo "Starting Podly..."
docker run -it --rm \
    $DOCKER_RUNTIME \
    -p 5001:5001 \
    -v "$(pwd)/config:/app/config" \
    -v "$(pwd)/in:/app/in" \
    -v "$(pwd)/processing:/app/processing" \
    -v "$(pwd)/srv:/app/srv" \
    podly-app 