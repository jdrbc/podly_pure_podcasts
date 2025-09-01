# Podly Frontend

This is the React + TypeScript + Vite frontend for Podly. The frontend is built and served as part of the main Podly application.

## Development

The frontend is integrated into the main Podly application and served as static assets by the Flask backend on port 5001.

### Development Workflows

1. **Backend Development**: Use `./run_podly.sh` (from project root)

   - Builds frontend once at startup
   - Good for backend development when frontend changes are infrequent

2. **Frontend Development**: Use `./run_podly.sh --dev` (from project root)

   - Automatically rebuilds frontend assets when files change
   - Watches `frontend/src/`, `package.json`, and `package-lock.json`
   - Requires `fswatch` (macOS) or `inotify-tools` (Linux) for file watching

3. **Direct Frontend Development**: You can still run the frontend development server separately for advanced frontend work:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   This starts the Vite development server on port 5173 with hot reloading and proxies API calls to the backend on port 5001.

### File Watcher Setup

For `./run_podly.sh --dev` to work optimally, install a file watcher:

**macOS**:

```bash
brew install fswatch
```

**Ubuntu/Debian**:

```bash
sudo apt-get install inotify-tools
```

Without a file watcher, you'll need to restart the application manually to see frontend changes.

## Build Process

The frontend build process depends on how you're running the application:

1. **Standard Mode** (`./run_podly.sh`): Frontend is built once using `npm run build` and static files are served by Flask from port 5001
2. **Development Mode** (`./run_podly.sh --dev`): Frontend is initially built, then automatically rebuilt when source files change
3. **Direct Development** (`npm run dev`): Vite dev server serves files with hot reloading on port 5173 and proxies API calls to backend on port 5001
4. **Docker**: Multi-stage build compiles frontend assets during image creation and copies them to the Flask static directory

### Development Asset Rebuilding

When using `./run_podly.sh --dev`, the system:

- Monitors `frontend/src/`, `frontend/package.json`, and `frontend/package-lock.json` for changes
- Automatically runs `npm run build` when changes are detected
- Copies the built assets to `src/app/static/` for Flask to serve
- Logs build output to `frontend-build.log`

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
