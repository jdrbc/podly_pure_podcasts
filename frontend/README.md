# Podly Frontend

This is the React + TypeScript + Vite frontend for Podly. The frontend is built and served as part of the main Podly application.

## Development

The frontend is integrated into the main Podly application. When running the application with Docker or the run scripts, the frontend is automatically built and served by the Flask backend.

For frontend development:

1. **Using Docker**: The frontend is automatically built during the Docker build process
2. **Using run scripts**: The frontend is built and served by the Flask application
3. **Direct development**: You can run the frontend development server separately:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   This will start the Vite development server with hot reloading.

## Build Process

The frontend build process:

1. **Development**: Vite dev server serves files directly
2. **Production**: Frontend is built using `npm run build` and static files are served by Flask
3. **Docker**: Multi-stage build compiles frontend assets and copies them to the Flask static directory

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
- **Tailwind Config**: `tailwind.config.js` for styling configuration
