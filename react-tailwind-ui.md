# Podly React+Tailwind UI Implementation Plan

## Overview

This document outlines the plan for implementing a modern React frontend with Tailwind CSS for the Podly podcast ad-removal application. The implementation supports both Docker and non-Docker environments.

## Project Architecture

### Backend (Existing Flask API)
- Maintain the current Flask backend as an API server
- Update routes to return JSON responses instead of rendering templates
- Add CORS support for cross-origin requests during development

### Frontend (New React Application)
- Create a standalone React application with Tailwind CSS
- Implement responsive UI for all existing features
- Communicate with Flask backend via RESTful API calls

## Tech Stack

- **Frontend**:
  - React 18+ (with TypeScript)
  - Vite (build tool)
  - Tailwind CSS (styling)
  - React Router (routing)
  - Tanstack Query (data fetching)
  - React Testing Library (testing)

- **Backend**:
  - Existing Flask API (with JSON endpoints)
  - SQLAlchemy (database ORM)
  - Whisper/GPT for podcast processing

## Implementation Plan

### 1. Frontend Setup

1. **Initialize React Project**:
   ```bash
   mkdir -p frontend
   cd frontend
   npm create vite@latest . -- --template react-ts
   npm install
   ```

2. **Install and Configure Tailwind CSS**:
   ```bash
   npm install -D tailwindcss postcss autoprefixer
   npx tailwindcss init -p
   ```

3. **Install Additional Dependencies**:
   ```bash
   npm install react-router-dom @tanstack/react-query axios clsx tailwind-merge
   ```

### 2. Core Components Development

#### Layout Components
- **AppLayout**: Main layout with navigation and content area
- **Navbar**: Application header with logo and navigation links
- **Footer**: Application footer with links and information
- **Container**: Reusable container with responsive padding

#### Feed Management
- **FeedList**: Display all podcast feeds with expandable details
- **AddFeedForm**: Form to add new podcast feeds
- **FeedDetails**: Expanded view showing podcast episodes
- **DeleteFeedModal**: Confirmation modal for feed deletion

#### Podcast Management
- **PodcastList**: Display episodes within a feed
- **PodcastItem**: Individual podcast episode with controls
- **WhitelistToggle**: Toggle to whitelist/blacklist episodes
- **DownloadButton**: Button to download processed episodes
- **BulkActions**: Component for batch operations

#### Podcast Player
- **AudioPlayer**: Custom audio player for processed podcasts
- **PlayerControls**: Play/pause/skip controls
- **ProgressBar**: Visual progress indicator
- **VolumeControl**: Audio volume adjustment

#### Podcast Details
- **PodcastDetails**: Detailed view of an individual podcast
- **TranscriptViewer**: Display podcast transcript
- **AdSegmentHighlighter**: Highlight detected ad segments

### 3. API Integration

Create services to interact with the Flask backend:

#### API Services
- **FeedService**: 
  - `getFeedsApi()`: Get all feeds
  - `addFeedApi(url)`: Add a new feed
  - `deleteFeedApi(id)`: Delete a feed
  - `refreshFeedApi(id)`: Refresh a feed

- **PodcastService**:
  - `getPodcastsApi(feedId)`: Get podcasts for a feed
  - `getPodcastDetailsApi(guid)`: Get podcast details
  - `downloadPodcastApi(guid)`: Download a processed podcast
  - `toggleWhitelistApi(guid, status)`: Update whitelist status

- **ProcessingService**:
  - `downloadAllPodcastsApi()`: Trigger batch download
  - `getProcessingStatusApi()`: Check processing status

### 4. Pages Development

- **HomePage**: Main landing page with feed listing
- **PodcastPage**: Detailed view for a podcast episode
- **NotFoundPage**: 404 page for invalid routes

### 5. Docker Configuration

#### Frontend Dockerfile
```dockerfile
# Build stage
FROM node:18-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Production stage
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

#### Updated docker-compose.yml
```yaml
services:
  backend:
    container_name: podly_backend
    image: podly-backend
    volumes:
      - ./config:/app/config
      - ./in:/app/in
      - ./srv:/app/srv
      - ./src:/app/src
      - ./scripts:/app/scripts
    build:
      context: .
      dockerfile: docker/backend/Dockerfile
      args:
        - BASE_IMAGE=${BASE_IMAGE:-python:3.11-slim}
        - CUDA_VERSION=${CUDA_VERSION:-12.1}
        - USE_GPU=${USE_GPU:-false}
        - USE_GPU_NVIDIA=${USE_GPU_NVIDIA:-false}
        - USE_GPU_RADEON=${USE_GPU_RADEON:-false}
    ports:
      - 5002:5002
    environment:
      - PUID=${PUID:-1000}
      - PGID=${PGID:-1000}
      - CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:--1}
      - CORS_ORIGINS=http://localhost:5002,http://localhost:80

  frontend:
    container_name: podly_frontend
    image: podly-frontend
    build:
      context: .
      dockerfile: docker/frontend/Dockerfile
    ports:
      - 5002:80
    depends_on:
      - backend
```

#### Development docker-compose.yml
```yaml
services:
  backend:
    # Same as production backend
    environment:
      - CORS_ORIGINS=http://localhost:5001
      - FLASK_ENV=development

  frontend-dev:
    container_name: podly_frontend_dev
    image: node:18-alpine
    volumes:
      - ./frontend:/app
    working_dir: /app
    command: sh -c "npm install && npm run dev"
    ports:
      - 5001:5001
    environment:
      - VITE_API_URL=http://localhost:5002
      - VITE_BASE_URL=/
      - NODE_ENV=development
    depends_on:
      - backend
```

### 6. Non-Docker Development Setup

#### Setup Scripts

1. **setup_frontend.sh**:
```bash
#!/bin/bash
cd frontend
npm install
echo "Frontend dependencies installed successfully!"
```

2. **run_frontend.sh**:
```bash
#!/bin/bash
cd frontend
npm run dev
```

#### Local Development

For non-Docker development:
1. Run the backend: `pipenv run python src/main.py`
2. Run the frontend: `cd frontend && npm run dev`

### 7. Backend API Updates

Maintain flask routes returning html - we want to keep the old UI running for now.
When new endpoints are needed for the frontend, then:
- Endpoint should be under /api/ 
- return JSON data
- Add CORS support
- Implement new endpoints as needed

Example modifications:
```python
# Add to app/__init__.py
from flask_cors import CORS

def create_app(test_config=None):
    app = Flask(__name__)
    # ...
    
    # Configure CORS
    cors_origins = os.environ.get('CORS_ORIGINS', 'http://localhost:5001').split(',')
    CORS(app, resources={r"/*": {"origins": cors_origins}})
    
    # ...
    return app

# Update routes.py endpoints
@main_bp.route("/api/feeds", methods=["GET"])
def get_feeds_api():
    feeds = Feed.query.all()
    return jsonify([{
        "id": feed.id,
        "title": feed.title,
        "rss_url": feed.rss_url,
        "posts_count": len(feed.posts)
    } for feed in feeds])
```

## Project Structure

```
podly_pure_podcasts/
├── src/                   # Existing Flask backend
├── frontend/              # New React frontend
│   ├── src/
│   │   ├── components/    # React components
│   │   ├── pages/         # Page components
│   │   ├── services/      # API services
│   │   ├── hooks/         # Custom React hooks
│   │   ├── types/         # TypeScript types
│   │   ├── utils/         # Utility functions
│   │   ├── assets/        # Static assets
│   │   └── App.tsx        # Main app component
│   ├── public/            # Static files
│   ├── vite.config.ts     # Vite configuration
│   ├── tailwind.config.js # Tailwind configuration
│   └── package.json       # Frontend dependencies
├── docker/                # Docker configuration files
│   ├── frontend/          # Frontend Docker files
│   ├── backend/           # Backend Docker files
│   └── nginx/             # Nginx configuration for production
├── docker-compose.yml     # Production docker-compose
├── docker-compose.dev.yml # Development docker-compose
└── scripts/               # Helper scripts
    ├── setup_frontend.sh  # Frontend setup script
    └── run_frontend.sh    # Frontend development script
```

## Implementation Steps

### Phase 1: Setup and Basic Structure (1-2 days)
- Set up React project with Tailwind CSS
- Create the core layout components
- Implement basic routing
- Configure development environment

### Phase 2: Feed Management (2-3 days)
- Implement feed listing UI
- Create add/delete feed functionality
- Implement basic podcast listing
- Connect to backend API endpoints

### Phase 3: Podcast Management (3-4 days)
- Implement podcast listing and details
- Create whitelist toggle functionality
- Add download controls
- Implement bulk actions

### Phase 4: Audio Player and Details (2-3 days)
- Build custom audio player
- Implement transcript viewer
- Add ad segment highlighting
- Create podcast details page

### Phase 5: Docker and Deployment (1-2 days)
- Configure Docker for development and production
- Update documentation
- Setup CI/CD pipeline
- Test in production environment

## UI Design Guidelines

- **Color Scheme**: Use a consistent color palette based on Podly's branding
- **Typography**: Use readable fonts optimized for web (Inter or system fonts)
- **Components**: Follow common UI patterns and accessibility standards
- **Responsiveness**: Design for mobile-first with appropriate breakpoints
- **Dark/Light Mode**: Support for system preference theme switching

## Accessibility Considerations

- Ensure proper contrast ratios
- Implement keyboard navigation
- Add ARIA attributes where necessary
- Support screen readers with proper semantic HTML

## Testing Strategy

- **Unit Tests**: Test individual components
- **Integration Tests**: Test component interactions
- **E2E Tests**: Test complete user flows
- **Accessibility Tests**: Ensure WCAG compliance

## Conclusion

This implementation plan provides a roadmap for creating a modern, responsive UI for the Podly podcast application using React and Tailwind CSS. The approach supports both Docker and non-Docker environments and maintains compatibility with the existing backend services.
