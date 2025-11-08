#!/bin/bash

# Colors for output
YELLOW='\033[1;33m'
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Central configuration defaults
CUDA_VERSION="12.4.1"
ROCM_VERSION="6.4"
CPU_BASE_IMAGE="python:3.11-slim"
GPU_NVIDIA_BASE_IMAGE="nvidia/cuda:${CUDA_VERSION}-cudnn-devel-ubuntu22.04"
GPU_ROCM_BASE_IMAGE="rocm/dev-ubuntu-22.04:${ROCM_VERSION}-complete"

# Read server URL from config.yml if it exists
SERVER_URL=""

if [ -f "config/config.yml" ]; then
    SERVER_URL=$(grep "^server:" config/config.yml | cut -d' ' -f2- | tr -d ' ')

    if [ -n "$SERVER_URL" ]; then
        # Remove http:// or https:// prefix to get just the hostname
        CLEAN_URL=$(echo "$SERVER_URL" | sed 's|^https\?://||')
        export VITE_API_URL="http://${CLEAN_URL}:5001"
        echo -e "${GREEN}Using server URL from config.yml: ${VITE_API_URL}${NC}"
    fi
fi

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
PRODUCTION_MODE=true
REBUILD=false
BRANCH_SUFFIX="main"
LITE_BUILD=false

# Detect NVIDIA GPU
NVIDIA_GPU_AVAILABLE=false
if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null; then
    NVIDIA_GPU_AVAILABLE=true
    echo -e "${GREEN}NVIDIA GPU detected.${NC}"
fi
# Detect ROCM GPU
AMD_GPU_AVAILABLE=false
if command -v rocm-smi &> /dev/null && rocm-smi &> /dev/null; then
    AMD_GPU_AVAILABLE=true
    echo -e "${GREEN}ROCM GPU detected.${NC}"
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
            GPU_NVIDIA_BASE_IMAGE="nvidia/cuda:${CUDA_VERSION}-cudnn-devel-ubuntu22.04"
            ;;
        --rocm=*)
            ROCM_VERSION="${1#*=}"
            GPU_ROCM_BASE_IMAGE="rocm/dev-ubuntu-22.04:${ROCM_VERSION}-complete"
            ;;
        -d|--detach|-b|--background)
            DETACHED=true
            ;;
        --dev)
            REBUILD=true
            PRODUCTION_MODE=false
            ;;
        --rebuild)
            REBUILD=true
            ;;
        --production)
            PRODUCTION_MODE=true
            ;;
        --branch=*)
            BRANCH_NAME="${1#*=}"
            BRANCH_SUFFIX="${BRANCH_NAME}"
            ;;
        --lite)
            LITE_BUILD=true
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --build             Build containers only (don't start)"
            echo "  --test-build        Test build with no cache"
            echo "  --gpu               Force GPU mode"
            echo "  --cpu               Force CPU mode"
            echo "  --cuda=VERSION      Specify CUDA version"
            echo "  --rocm=VERSION      Specify ROCM version"
            echo "  -d, --detach        Run in detached/background mode"
            echo "  -b, --background    Alias for --detach"
            echo "  --dev               Development mode (rebuild containers)"
            echo "  --rebuild           Rebuild containers before starting"
            echo "  --production        Use published images (default)"
            echo "  --branch=BRANCH     Use specific branch images"
            echo "  --lite              Build without Whisper (smaller image, remote transcription only)"
            echo "  -h, --help          Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--build] [--test-build] [--gpu] [--cpu] [--cuda=VERSION] [--rocm=VERSION] [-d|--detach] [-b|--background] [--dev] [--rebuild] [--production] [--branch=BRANCH_NAME] [--lite] [-h|--help]"
            exit 1
            ;;
    esac
    shift
done

# Determine if GPU should be used based on availability and flags
USE_GPU=false
USE_GPU_NVIDIA=false
USE_GPU_AMD=false
if [ "$FORCE_CPU" = true ]; then
    USE_GPU=false
    echo -e "${YELLOW}Forcing CPU mode${NC}"
elif [ "$FORCE_GPU" = true ]; then
    if [ "$NVIDIA_GPU_AVAILABLE" = true ]; then
        USE_GPU=true
        USE_GPU_NVIDIA=true
        echo -e "${YELLOW}Forcing GPU mode (NVIDIA detected)${NC}"
    elif [ "$AMD_GPU_AVAILABLE" = true ]; then
        USE_GPU=true
        USE_GPU_AMD=true
        echo -e "${YELLOW}Forcing GPU mode (AMD detected)${NC}"
    else
        echo -e "${RED}Error: GPU requested but no compatible GPU detected. Please install NVIDIA or AMD GPU drivers.${NC}"
        exit 1
    fi
elif [ "$NVIDIA_GPU_AVAILABLE" = true ]; then
    USE_GPU=true
    USE_GPU_NVIDIA=true
    echo -e "${YELLOW}Using GPU mode (auto-detected)${NC}"
elif [ "${AMD_GPU_AVAILABLE}" = true ]; then
    USE_GPU=true
    USE_GPU_AMD=true
    echo -e "${YELLOW}Using GPU mode (auto-detected)${NC}"
else
    echo -e "${YELLOW}Using CPU mode (no GPU detected)${NC}"
fi

# Set base image and CUDA environment
if [ "$USE_GPU_NVIDIA" = true ]; then
    BASE_IMAGE="$GPU_NVIDIA_BASE_IMAGE"
    CUDA_VISIBLE_DEVICES=0
elif [ "${USE_GPU_AMD}" = true ]; then
    BASE_IMAGE="${GPU_ROCM_BASE_IMAGE}"
    CUDA_VISIBLE_DEVICES=0
else
    BASE_IMAGE="$CPU_BASE_IMAGE"
    CUDA_VISIBLE_DEVICES=-1
fi

# Get current user's UID and GID
export PUID=$(id -u)
export PGID=$(id -g)
export BASE_IMAGE
export CUDA_VERSION
export ROCM_VERSION
export CUDA_VISIBLE_DEVICES
export USE_GPU
export USE_GPU_NVIDIA
export USE_GPU_AMD
export LITE_BUILD

# Surface authentication/session configuration warnings
REQUIRE_AUTH_LOWER=$(printf '%s' "${REQUIRE_AUTH:-false}" | tr '[:upper:]' '[:lower:]')
if [ "$REQUIRE_AUTH_LOWER" = "true" ]; then
    if [ -z "${PODLY_SECRET_KEY}" ]; then
        echo -e "${YELLOW}Warning: REQUIRE_AUTH is true but PODLY_SECRET_KEY is not set. Sessions will be reset on every restart.${NC}"
    fi

fi

# Setup Docker Compose configuration
if [ "$PRODUCTION_MODE" = true ]; then
    COMPOSE_FILES="-f compose.yml"
    # Set branch tag based on GPU detection and branch
    if [ "$LITE_BUILD" = true ] && [ "$USE_GPU" = true ]; then
        echo -e "${RED}Error: --lite cannot be combined with GPU builds. Use --cpu or drop --lite.${NC}"
        exit 1
    fi

    if [ "$LITE_BUILD" = true ]; then
        BRANCH="${BRANCH_SUFFIX}-lite"
    elif [ "$USE_GPU_NVIDIA" = true ]; then
        BRANCH="${BRANCH_SUFFIX}-gpu-nvidia"
    elif [ "$USE_GPU_AMD" = true ]; then
        BRANCH="${BRANCH_SUFFIX}-gpu-amd"
    else
        BRANCH="${BRANCH_SUFFIX}-latest"
    fi

    export BRANCH

    echo -e "${YELLOW}Production mode - using published images${NC}"
    echo -e "${YELLOW}  Branch tag: ${BRANCH}${NC}"
    if [ "$BRANCH_SUFFIX" != "main" ]; then
        echo -e "${GREEN}Using custom branch: ${BRANCH_SUFFIX}${NC}"
    fi
else
    COMPOSE_FILES="-f compose.dev.cpu.yml"
    if [ "$USE_GPU_NVIDIA" = true ]; then
        COMPOSE_FILES="$COMPOSE_FILES -f compose.dev.nvidia.yml"
    fi
    if [ "$USE_GPU_AMD" = true ]; then
        COMPOSE_FILES="$COMPOSE_FILES -f compose.dev.rocm.yml"
    fi
    if [ "$REBUILD" = true ]; then
        echo -e "${YELLOW}Rebuild mode - will rebuild containers before starting${NC}"
    fi
    if [ "$LITE_BUILD" = true ]; then
        echo -e "${YELLOW}Lite mode - building without Whisper (remote transcription only)${NC}"
    fi
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
    # Handle development rebuild
    if [ "$REBUILD" = true ]; then
        echo -e "${YELLOW}Rebuilding containers...${NC}"
        docker compose $COMPOSE_FILES build
    fi

    if [ "$DETACHED" = true ]; then
        echo -e "${YELLOW}Starting Podly in detached mode...${NC}"
        docker compose $COMPOSE_FILES up -d
        echo -e "${GREEN}Podly is running in the background.${NC}"
        echo -e "${GREEN}Application: http://localhost:5001${NC}"
    else
        echo -e "${YELLOW}Starting Podly...${NC}"
        echo -e "${GREEN}Application will be available at: http://localhost:5001${NC}"
        docker compose $COMPOSE_FILES up
    fi
fi
