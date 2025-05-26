#!/bin/bash

# Colors for output
YELLOW='\033[1;33m'
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Central configuration defaults
CUDA_VERSION="12.1"
CPU_BASE_IMAGE="python:3.11-slim"
GPU_BASE_IMAGE="nvidia/cuda:${CUDA_VERSION}-cudnn-devel-ubuntu22.04"

# Check dependencies
echo -e "${YELLOW}Checking dependencies...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker not found. Please install Docker first.${NC}"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo -e "${RED}Docker Compose not found. Please install Docker Compose V2.${NC}"
    exit 1
fi

# Default values
BUILD_ONLY=false
TEST_BUILD=false
FORCE_CPU=false
FORCE_GPU=false
DETACHED=false
DEV_MODE=false

# Detect NVIDIA GPU
NVIDIA_GPU_AVAILABLE=false
if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null; then
    NVIDIA_GPU_AVAILABLE=true
    echo -e "${GREEN}NVIDIA GPU detected.${NC}"
fi

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --build)
            BUILD_ONLY=true
            ;;
        --test-build)
            TEST_BUILD=true
            ;;
        --gpu)
            FORCE_GPU=true
            ;;
        --cpu)
            FORCE_CPU=true
            ;;
        --cuda=*)
            CUDA_VERSION="${1#*=}"
            GPU_BASE_IMAGE="nvidia/cuda:${CUDA_VERSION}-cudnn-devel-ubuntu22.04"
            ;;
        -d|--detach)
            DETACHED=true
            ;;
        --dev)
            DEV_MODE=true
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--build] [--test-build] [--gpu] [--cpu] [--cuda=VERSION] [-d|--detach] [--dev]"
            exit 1
            ;;
    esac
    shift
done

# Determine if GPU should be used based on availability and flags
USE_GPU=false
if [ "$FORCE_CPU" = true ]; then
    USE_GPU=false
    echo -e "${YELLOW}Forcing CPU mode${NC}"
elif [ "$FORCE_GPU" = true ]; then
    if [ "$NVIDIA_GPU_AVAILABLE" = false ]; then
        echo -e "${RED}Warning: GPU requested but no NVIDIA GPU detected. Build may fail.${NC}"
    fi
    USE_GPU=true
    echo -e "${YELLOW}Forcing GPU mode${NC}"
elif [ "$NVIDIA_GPU_AVAILABLE" = true ]; then
    USE_GPU=true
    echo -e "${YELLOW}Using GPU mode (auto-detected)${NC}"
else
    echo -e "${YELLOW}Using CPU mode (no GPU detected)${NC}"
fi

# Set base image and CUDA environment
if [ "$USE_GPU" = true ]; then
    BASE_IMAGE="$GPU_BASE_IMAGE"
    CUDA_VISIBLE_DEVICES=0
else
    BASE_IMAGE="$CPU_BASE_IMAGE"
    CUDA_VISIBLE_DEVICES=-1
fi

# Ensure directories exist
mkdir -p config in srv scripts

# Get current user's UID and GID
export PUID=$(id -u)
export PGID=$(id -g)
export BASE_IMAGE
export CUDA_VERSION
export CUDA_VISIBLE_DEVICES
export USE_GPU

# Setup Docker Compose configuration
COMPOSE_FILES="-f compose.yml"
if [ "$USE_GPU" = true ]; then
    COMPOSE_FILES="$COMPOSE_FILES -f compose.nvidia.yml"
fi
if [ "$DEV_MODE" = true ]; then
    COMPOSE_FILES="$COMPOSE_FILES -f compose.dev.yml"
    echo -e "${YELLOW}Development mode enabled - frontend will run with hot reloading${NC}"
fi

# Execute appropriate Docker Compose command
if [ "$BUILD_ONLY" = true ]; then
    echo -e "${YELLOW}Building containers only...${NC}"
    docker compose $COMPOSE_FILES build
    echo -e "${GREEN}Build completed successfully.${NC}"
elif [ "$TEST_BUILD" = true ]; then
    echo -e "${YELLOW}Testing build with no cache...${NC}"
    docker compose $COMPOSE_FILES build --no-cache
    echo -e "${GREEN}Test build completed successfully.${NC}"
else
    if [ "$DETACHED" = true ]; then
        echo -e "${YELLOW}Starting Podly in detached mode...${NC}"
        docker compose $COMPOSE_FILES up -d
        echo -e "${GREEN}Podly is running in the background.${NC}"
        echo -e "${GREEN}Frontend: http://localhost:5002${NC}"
        echo -e "${GREEN}Backend API: http://localhost:5001${NC}"
    else
        echo -e "${YELLOW}Starting Podly...${NC}"
        echo -e "${GREEN}Frontend will be available at: http://localhost:5002${NC}"
        echo -e "${GREEN}Backend API will be available at: http://localhost:5001${NC}"
        docker compose $COMPOSE_FILES up
    fi
fi 