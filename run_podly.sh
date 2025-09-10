#!/bin/bash

# Colors for output
YELLOW='\033[1;33m'
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Default values
BACKGROUND_MODE=false
LITE_BUILD=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -b|--background|-d|--detach)
            BACKGROUND_MODE=true
            ;;
        --lite)
            LITE_BUILD=true
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "This script is for local development only."
            echo "For production deployment, use run_podly_docker.sh instead."
            echo ""
            echo "Options:"
            echo "  -b, --background    Run in background mode"
            echo "  -d, --detach        Alias for --background"
            echo "  --lite              Install without Whisper (remote transcription only)"
            echo "  -h, --help          Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
    shift
done

# Function to cleanup background processes
cleanup() {
    echo -e "\n${YELLOW}Shutting down Podly...${NC}"
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null
        echo -e "${GREEN}Backend stopped${NC}"
    fi
    exit 0
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

echo -e "${BOLD}${BLUE}Starting Podly...${NC}"

# Check dependencies
echo -e "${YELLOW}Checking dependencies...${NC}"

# Check if pipenv is installed
if ! command -v pipenv &> /dev/null; then
    echo -e "${RED}pipenv not found. Please install pipenv first:${NC}"
    echo -e "${RED}  pip install pipenv${NC}"
    exit 1
fi

# Check if npm is installed
if ! command -v npm &> /dev/null; then
    echo -e "${RED}npm not found. Please install Node.js and npm first.${NC}"
    exit 1
fi

# Check if config file exists
CONFIG_FILE="config/config.yml"
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}Configuration file not found: $CONFIG_FILE${NC}"
    echo -e "${RED}Please copy config/config.yml.example to config/config.yml and configure it.${NC}"
    exit 1
fi

# Set up environment variables from config.yml
echo -e "${YELLOW}Setting up environment from config.yml...${NC}"

# Read configuration from config.yml
APP_PORT=$(grep "^port:" "$CONFIG_FILE" | cut -d' ' -f2- | tr -d ' ')

# Default values
if [ -z "$APP_PORT" ]; then
    APP_PORT="5001"
fi

# For this combined setup, the backend serves both API and frontend on the same port
BACKEND_PORT="$APP_PORT"

# Set the API URL for the frontend build (backend runs on the configured port)
export VITE_API_URL="http://localhost:${BACKEND_PORT}"

# CORS is now configured to wildcard by default in the app
# Users can override with CORS_ORIGINS environment variable if needed

echo -e "${GREEN}Environment configured:${NC}"
echo -e "  Application: http://localhost:${BACKEND_PORT}"
echo -e "  CORS: Wildcard (*) - override with CORS_ORIGINS env var if needed"
if [ "$LITE_BUILD" = true ]; then
    echo -e "  ${YELLOW}Lite mode: Local Whisper disabled, use remote transcription services${NC}"
fi

# Check if pipenv environment exists
if ! pipenv --venv &> /dev/null; then
    echo -e "${YELLOW}Setting up Python virtual environment...${NC}"
    pipenv --python 3.11
    if [ "$LITE_BUILD" = true ]; then
        echo -e "${YELLOW}Installing dependencies without Whisper (lite mode)...${NC}"
        # Use the lite Pipfile for installation
        cp Pipfile.lite Pipfile
        pipenv install
        # Restore original Pipfile
        git checkout Pipfile 2>/dev/null || cp Pipfile.lite Pipfile.backup
    else
        echo -e "${YELLOW}Installing full dependencies including Whisper...${NC}"
        pipenv install
    fi
else
    # Check if dependencies need updating
    if ! pipenv verify &> /dev/null; then
        echo -e "${YELLOW}Updating Python dependencies...${NC}"
        if [ "$LITE_BUILD" = true ]; then
            echo -e "${YELLOW}Syncing lite dependencies...${NC}"
            cp Pipfile.lite Pipfile
            pipenv sync
            git checkout Pipfile 2>/dev/null || cp Pipfile.lite Pipfile.backup
        else
            pipenv sync
        fi
    fi
fi

# Check if frontend dependencies are installed and build static assets
if [ ! -d "frontend/node_modules" ]; then
    echo -e "${YELLOW}Installing frontend dependencies...${NC}"
    cd frontend || exit 1
    npm install
    cd .. || exit 1
else
    # Check if package-lock.json is newer than node_modules
    if [ "frontend/package-lock.json" -nt "frontend/node_modules" ]; then
        echo -e "${YELLOW}Updating frontend dependencies...${NC}"
        cd frontend || exit 1
        npm ci
        cd .. || exit 1
    fi
fi

# Always build frontend assets fresh for development
echo -e "${YELLOW}Building frontend assets...${NC}"
cd frontend || exit 1
npm run build
cd .. || exit 1

# Copy built frontend assets to Flask static folder
echo -e "${YELLOW}Copying frontend assets to backend static folder...${NC}"
mkdir -p src/app/static
rm -rf src/app/static/*
if [ -d "frontend/dist" ]; then
    cp -r frontend/dist/* src/app/static/
else
    echo -e "${RED}Error: Frontend build failed - dist directory not found${NC}"
    exit 1
fi

# Start backend server (which now serves both API and frontend)
echo -e "${YELLOW}Starting backend server...${NC}"
if [ "$BACKGROUND_MODE" = true ]; then
    nohup pipenv run python src/main.py > backend.log 2>&1 &
    BACKEND_PID=$!
    disown
else
    pipenv run python src/main.py > backend.log 2>&1 &
    BACKEND_PID=$!
fi

# Wait a moment for backend to start
sleep 3

# Note: For frontend reloading during development, restart this script after making changes

if [ "$BACKGROUND_MODE" = true ]; then
    echo -e "${BOLD}${GREEN}🎉 PODLY RUNNING IN BACKGROUND${NC}"
    echo -e "${GREEN}Application: http://localhost:${BACKEND_PORT}${NC}"
    echo -e "${YELLOW}Logs: backend.log${NC}"
    echo -e "${YELLOW}To stop: kill $BACKEND_PID${NC}"
    exit 0
fi

# Clear screen and show running interface
clear

cat << 'EOF'
 ____   ___  ____  _  __   __
|  _ \ / _ \|  _ \| | \ \ / /
| |_) | | | | | | | |  \ V /
|  __/| |_| | |_| | |___| |
|_|    \___/|____/|_____|_|

EOF

echo -e "${BOLD}${GREEN}🎉 PODLY RUNNING${NC}"
echo -e "${GREEN}Application: http://localhost:${BACKEND_PORT}${NC}"
echo -e "${YELLOW}Development mode: Restart script to reload frontend changes${NC}"
echo ""
echo -e "${YELLOW}Controls:${NC}"
echo -e "  ${BOLD}[b]${NC}        Run in background"
echo -e "  ${BOLD}[Ctrl+C]${NC}  Kill & quit"
echo ""
echo -e "${BLUE}Press any key to see logs, or use controls above...${NC}"

# Handle user input
while true; do
    read -n 1 -s key
    case $key in
        b|B)
            echo -e "\n${YELLOW}Moving to background mode...${NC}"
            echo -e "${GREEN}Podly is now running in the background${NC}"
            echo -e "${YELLOW}Backend PID: $BACKEND_PID${NC}"
            echo -e "${YELLOW}To stop: kill $BACKEND_PID${NC}"
            echo -e "${YELLOW}Alternate kill command: pkill -f 'python src/main.py'${NC}"
            exit 0
            ;;
        *)
            # Show recent logs
            clear
            echo -e "${BOLD}${BLUE}=== RECENT LOGS ===${NC}"
            echo -e "${YELLOW}Backend (last 20 lines):${NC}"
            tail -n 20 backend.log 2>/dev/null || echo "No backend logs yet"
            echo ""
            echo -e "${BLUE}Press [b] for background mode, [Ctrl+C] to quit, or any key to refresh logs...${NC}"
            ;;
    esac
done
