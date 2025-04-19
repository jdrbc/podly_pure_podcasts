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

# Check for command-line flags
FORCE_CPU=false
FORCE_GPU=false
BUILD_ONLY=false
TEST_BUILD=false

while (( "$#" )); do
  case "$1" in
    --cpu)
      FORCE_CPU=true
      shift
      ;;
    --gpu)
      FORCE_GPU=true
      shift
      ;;
    --build)
      BUILD_ONLY=true
      shift
      ;;
    --test-build)
      TEST_BUILD=true
      shift
      ;;
    --help)
      echo "Usage: ./run_podly_docker.sh [OPTIONS]"
      echo "Options:"
      echo "  --cpu         Force CPU mode even if GPU is available"
      echo "  --gpu         Force GPU mode (will fail if GPU is not available)"
      echo "  --build       Only build the Docker images, don't start containers"
      echo "  --test-build  Test if the Docker build works (uses 'docker build' directly)"
      echo "  --dev         Run in development mode with auto-reloading"
      echo "  --help        Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# Special case for test-build
if [ "$TEST_BUILD" = true ]; then
    echo -e "${YELLOW}Testing Docker build process...${NC}"
    if docker build -t podly-test .; then
        echo -e "${GREEN}Build test successful!${NC}"
        exit 0
    else
        echo -e "${RED}Build test failed.${NC}"
        exit 1
    fi
fi

# Check configuration file exists
if [ ! -f "config/config.yml" ]; then
    echo -e "${YELLOW}Warning: config/config.yml not found${NC}"
    echo -e "Creating from example file..."
    cp config/config.yml.example config/config.yml
    echo -e "${GREEN}Created config/config.yml. Please edit this file with your API keys and settings.${NC}"
fi

# Ensure log file exists and is writable
mkdir -p config
touch config/app.log
chmod 666 config/app.log

USE_GPU=false

# Only check for GPU if not forcing CPU mode
if [ "$FORCE_CPU" = false ]; then
    echo -e "${YELLOW}Checking for NVIDIA GPU...${NC}"
    if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null; then
        echo -e "${GREEN}NVIDIA GPU detected${NC}"
        USE_GPU=true
    elif [ "$FORCE_GPU" = true ]; then
        echo -e "${RED}No NVIDIA GPU detected but --gpu flag was specified. Cannot continue.${NC}"
        exit 1
    else
        echo -e "${YELLOW}No NVIDIA GPU detected, will use CPU configuration${NC}"
    fi
else
    echo -e "${YELLOW}Forcing CPU mode as requested${NC}"
fi

# Set up the docker-compose command
if [ "$USE_GPU" = true ]; then
    echo -e "${GREEN}Using NVIDIA GPU-accelerated configuration${NC}"
    DOCKER_CMD="docker compose -f compose.yml -f compose.nvidia.yml"
else
    echo -e "${YELLOW}Using standard CPU configuration${NC}"
    DOCKER_CMD="docker compose"
fi

export PODLY_COMMAND="python src/main.py"

# Regular build or run based on flags
if [ "$BUILD_ONLY" = true ]; then
    echo -e "${YELLOW}Building Docker images...${NC}"
    $DOCKER_CMD build
    echo -e "${GREEN}Build complete. Run without --build flag to start containers.${NC}"
else
    echo -e "${YELLOW}Starting Podly...${NC}"
    $DOCKER_CMD up
fi 