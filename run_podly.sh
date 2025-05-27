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

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -b|--background)
            BACKGROUND_MODE=true
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -b, --background    Run in background mode"
            echo "  -h, --help         Show this help message"
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
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null
        echo -e "${GREEN}Frontend stopped${NC}"
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

# Read server URL from config.yml
SERVER_URL=$(grep "^server:" "$CONFIG_FILE" | cut -d' ' -f2- | tr -d ' ')
BACKEND_PORT=$(grep "^backend_server_port:" "$CONFIG_FILE" | cut -d' ' -f2- | tr -d ' ')
FRONTEND_PORT=$(grep "^frontend_server_port:" "$CONFIG_FILE" | cut -d' ' -f2- | tr -d ' ')

# Default values
if [ -z "$SERVER_URL" ]; then
    SERVER_URL="http://localhost"
fi
if [ -z "$BACKEND_PORT" ]; then
    BACKEND_PORT="5002"
fi
if [ -z "$FRONTEND_PORT" ]; then
    FRONTEND_PORT="5001"
fi

# Set the API URL for the frontend
export VITE_API_URL="${SERVER_URL}:${BACKEND_PORT}"

echo -e "${GREEN}Environment configured:${NC}"
echo -e "  Frontend: ${SERVER_URL}:${FRONTEND_PORT}"
echo -e "  Backend API: ${VITE_API_URL}"

# Check if pipenv environment exists
if ! pipenv --venv &> /dev/null; then
    echo -e "${YELLOW}Setting up Python virtual environment...${NC}"
    pipenv --python 3.11
    pipenv install
fi

# Check if frontend dependencies are installed
if [ ! -d "frontend/node_modules" ]; then
    echo -e "${YELLOW}Installing frontend dependencies...${NC}"
    cd frontend
    npm install
    cd ..
fi

# Start backend
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

# Start frontend
echo -e "${YELLOW}Starting frontend server...${NC}"
cd frontend
if [ "$BACKGROUND_MODE" = true ]; then
    nohup npm run dev > ../frontend.log 2>&1 &
    FRONTEND_PID=$!
    disown
else
    npm run dev > ../frontend.log 2>&1 &
    FRONTEND_PID=$!
fi
cd ..

# Wait a moment for frontend to start
sleep 3

if [ "$BACKGROUND_MODE" = true ]; then
    echo -e "${BOLD}${GREEN}🎉 PODLY RUNNING IN BACKGROUND${NC}"
    echo -e "${GREEN}Frontend: ${SERVER_URL}:${FRONTEND_PORT}${NC}"
    echo -e "${GREEN}Backend API: ${VITE_API_URL}${NC}"
    echo -e "${YELLOW}Logs:${NC}"
    echo -e "  Backend: backend.log"
    echo -e "  Frontend: frontend.log"
    echo -e "${YELLOW}To stop: kill $BACKEND_PID $FRONTEND_PID${NC}"
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
echo -e "${GREEN}Frontend: ${SERVER_URL}:${FRONTEND_PORT}${NC}"
echo -e "${GREEN}Backend API: ${VITE_API_URL}${NC}"
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
            echo -e "${YELLOW}Frontend PID: $FRONTEND_PID${NC}"
            echo -e "${YELLOW}To stop: kill $BACKEND_PID $FRONTEND_PID${NC}"
            echo -e "${YELLOW}Alternate kill command: (lsof -i :5001; lsof -i :5002) | grep LISTEN | awk '{print \$2}' | xargs kill -9${NC}"
            exit 0
            ;;
        *)
            # Show recent logs
            clear
            echo -e "${BOLD}${BLUE}=== RECENT LOGS ===${NC}"
            echo -e "${YELLOW}Backend (last 10 lines):${NC}"
            tail -n 10 backend.log 2>/dev/null || echo "No backend logs yet"
            echo ""
            echo -e "${YELLOW}Frontend (last 10 lines):${NC}"
            tail -n 10 frontend.log 2>/dev/null || echo "No frontend logs yet"
            echo ""
            echo -e "${BLUE}Press [b] for background mode, [Ctrl+C] to quit, or any key to refresh logs...${NC}"
            ;;
    esac
done 