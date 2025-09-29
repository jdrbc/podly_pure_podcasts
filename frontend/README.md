# Podly Frontend

This is the React + TypeScript + Vite frontend for Podly. The frontend is built and served as part of the main Podly application.

## Development

The frontend is integrated into the main Podly application and served as static assets by the Flask backend on port 5001.

### Development Workflows

1. **Docker (recommended)**: The Docker build compiles the frontend during image creation and serves static assets from Flask.

2. **Direct Frontend Development**: You can run the frontend development server separately for advanced frontend work:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   This starts the Vite development server on port 5173 with hot reloading and proxies API calls to the backend on port 5001.

### Build Process

- **Direct Development** (`npm run dev`): Vite dev server serves files with hot reloading on port 5173 and proxies API calls to backend on port 5001
- **Docker**: Multi-stage build compiles frontend assets during image creation and copies them to the Flask static directory

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
