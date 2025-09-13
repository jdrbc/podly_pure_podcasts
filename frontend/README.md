# Podly Frontend

This is the React + TypeScript + Vite frontend for Podly. The frontend is built and served as part of the main Podly application.

## Development

The frontend is integrated into the main Podly application and served as static assets by the Flask backend on port 5001.

### Development Workflows

1. **Local Development**: Use `./run_podly.sh` (from project root)

   - Always builds frontend fresh at startup
   - Restart the script after making frontend changes to rebuild assets
   - Focused on local development only

2. **Direct Frontend Development**: You can still run the frontend development server separately for advanced frontend work:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   This starts the Vite development server on port 5173 with hot reloading and proxies API calls to the backend on port 5001.

### Frontend Changes

To see frontend changes when using `./run_podly.sh`, restart the application. The script always builds frontend assets fresh on startup.

## Build Process

The frontend build process depends on how you're running the application:

1. **Local Development** (`./run_podly.sh`): Frontend is built fresh using `npm run build` and static files are served by Flask from port 5001
2. **Direct Development** (`npm run dev`): Vite dev server serves files with hot reloading on port 5173 and proxies API calls to backend on port 5001
3. **Docker**: Multi-stage build compiles frontend assets during image creation and copies them to the Flask static directory

### Development Asset Rebuilding

The `./run_podly.sh` script always builds frontend assets fresh on startup:

- Runs `npm run build` to compile the latest frontend code
- Copies the built assets to `src/app/static/` for Flask to serve
- To see frontend changes, restart the script

## Technology Stack

- **React 18+** with TypeScript
- **Vite** for build tooling and development server
- **Tailwind CSS** for styling
- **React Router** for client-side routing
- **Tanstack Query** for data fetching

## Configuration

The frontend configuration is handled through:

- **Environment Variables**: Set via Vite's environment variable system
- **Vite Config**: `vite.config.ts` for build and development settings
  - Development server runs on port 5173
  - Proxies API calls to backend on port 5001 (configurable via `BACKEND_TARGET`)
- **Tailwind Config**: `tailwind.config.js` for styling configuration
