<h2 align="center">
<img width="50%" src="src/app/static/images/logos/logo_with_text.png" />

</h2>

<p align="center">
<p align="center">Ad-block for podcasts. Create an ad-free RSS feed.</p>
<p align="center">
  <a href="https://discord.gg/FRB98GtF6N" target="_blank">
      <img src="https://img.shields.io/badge/discord-join-blue.svg?logo=discord&logoColor=white" alt="Discord">
  </a>
</p>

## Overview

Podly uses Whisper and Chat GPT to remove ads from podcasts.

Here's how it works:

- You request an episode
- Podly downloads the requested episode
- Whisper transcribes the episode
- Chat GPT labels ad segments
- Podly removes the ad segments
- Podly delivers the ad-free version of the podcast to you

## How To Run

For detailed setup instructions, see our [beginner's guide](docs/how_to_run_beginners.md).

### Quick Start - No Docker

1. Install dependencies:

   ```shell
   # Install ffmpeg
   sudo apt install ffmpeg  # Ubuntu/Debian
   # or
   brew install ffmpeg      # macOS

   # Install Python and Node.js dependencies
   pip install pipenv
   ```

2. Set up configuration:

   ```shell
   # Copy example config and edit
   cp config/config.yml.example config/config.yml
   # Edit config.yml and update llm_api_key with your key
   ```

3. Run Podly:

   ```shell
   # Make script executable
   chmod +x run_podly.sh

   # Start Podly (interactive mode)
   ./run_podly.sh

   # Or start in background mode
   ./run_podly.sh -b
   # Alternative: ./run_podly.sh -d

   # Note: For frontend changes, restart the script to rebuild assets
   ```

The script will automatically:

- Set up Python virtual environment
- Install and build frontend dependencies
- Copy frontend assets to backend static folder
- Configure environment variables from config.yml
- Start the unified application server on port 5001

### Quick Start - With Docker

1. Set up your configuration:

   ```bash
   cp config/config.yml.example config/config.yml
   # Edit config.yml with your settings
   ```

2. Run Podly with Docker:

   ```bash
   # Make the script executable first
   chmod +x run_podly_docker.sh

   # Start Podly (interactive mode)
   ./run_podly_docker.sh

   # Or start in background mode
   ./run_podly_docker.sh -d
   # Alternative: ./run_podly_docker.sh -b

   # For development with container rebuilding
   ./run_podly_docker.sh --dev
   ```

   This will automatically detect if you have an NVIDIA GPU and use it for acceleration.

## Usage

Once the server is running:

1. Open <http://localhost:5001> in your web browser
2. Add podcast RSS feeds through the web interface
3. Open your podcast app and subscribe to the Podly endpoint
   - For example, `http://localhost:5001/feed/1`
4. Select an episode & download
5. Wait patiently 😊 (Transcription takes about 1 minute per 15 minutes of podcast on an M3 MacBook)

## Transcription Options

Podly supports multiple options for audio transcription:

1. **Local Whisper (Default)** - Uses OpenAI's Whisper model running locally on your machine

   - See `config/config.yml.example` for configuration
   - Slower but doesn't require an external API (~ 1 minute per 15 minutes of podcast on an M3 MacBook)
   - **Note**: Not available in lite mode (`--lite` flag)

2. **OpenAI Hosted Whisper** - Uses OpenAI's hosted Whisper service

   - See `config/config_remote_whisper.yml.example` for configuration
   - Fast and accurate but requires OpenAI API credits

3. **Groq Hosted Whisper** - Uses Groq's hosted Whisper service
   - See `config/config_groq_whisper.yml.example` for configuration
   - Fast and cost-effective alternative to OpenAI

To use Groq for transcription, you'll need a Groq API key. Copy the `config/config_groq_whisper.yml.example` to `config/config.yml` and update the `api_key` field with your Groq API key.

### Lite Mode

For smaller deployments or when you only need remote transcription services, you can use the `--lite` flag with both run scripts:

```bash
# Docker lite mode (much smaller image, faster builds)
./run_podly_docker.sh --lite

# Local lite mode (faster setup, fewer dependencies)
./run_podly.sh --lite
```

**Lite mode benefits:**

- Significantly smaller Docker images (saves ~2GB)
- Faster installation and builds
- Reduced memory usage
- No PyTorch/CUDA dependencies

**Lite mode limitations:**

- Local Whisper transcription is not available
- Must use OpenAI, Groq, or other remote transcription services

**Lite mode configuration:**

When using lite mode, you must configure a remote transcription service in your `config/config.yml`. Add one of the following configurations:

#### Option 1: OpenAI Whisper (recommended for accuracy)

```yaml
whisper:
  whisper_type: remote
  model: whisper-1
  api_key: sk-proj-XXXXXXXXXXXXXXXXXXXXXXXX # Your OpenAI API key
  # Optional settings:
  # base_url: https://api.openai.com/v1  # Default OpenAI endpoint
  # language: "en"
  # timeout_sec: 600
  # chunksize_mb: 24
```

#### Option 2: Groq Whisper (recommended for speed and cost)

```yaml
whisper:
  whisper_type: groq
  api_key: gsk_XXXXXXXXXXXXXXXXXXXXXXXXXXXX # Your Groq API key
  model: whisper-large-v3-turbo
  language: en
  max_retries: 3
```

## Remote Setup

Podly works out of the box when running locally (see [Usage](#usage)). For remote deployment, the application automatically detects the requesting domain and generates appropriate URLs through request headers.

### Configuration Options

Podly provides flexible configuration options for different deployment scenarios:

#### Application Settings

```yaml
# Application server settings (optional)
host: 0.0.0.0 # Interface to listen on (default: 0.0.0.0, accepts all requests)
port: 5001 # Port to listen on (default: 5001)
```

### Reverse Proxy Setup

Podly automatically detects when it's running behind a reverse proxy and generates feed URLs using the requesting domain. This works seamlessly with most reverse proxy setups without any configuration.

#### How It Works

Podly uses request headers to determine the correct domain and protocol:

1. **X-Forwarded headers** (highest priority): `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Forwarded-Port`
2. **Host header** (fallback): Uses the `Host` header from the request
3. **Configuration** (last resort): Falls back to config when no request context

#### Example Results

- Request to `https://my.domain.com/feed/1` → generates URLs like `https://my.domain.com/api/posts/abc123/download`
- Request to `http://localhost:5001/feed/1` → generates URLs like `http://localhost:5001/api/posts/abc123/download`

#### Reverse Proxy Examples

**Nginx:**

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
    }
}
```

**Traefik (docker-compose.yml):**

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.podly.rule=Host(`your-domain.com`)"
  - "traefik.http.routers.podly.tls.certresolver=letsencrypt"
  - "traefik.http.services.podly.loadbalancer.server.port=5001"
```

> **Note**: Most modern reverse proxies automatically set the required headers. No manual configuration is needed in most cases.

### Basic Authentication

Podly supports basic authentication. See below for example setup for `httpd.conf`.

```
LoadModule proxy_module modules/mod_proxy.so
LoadModule proxy_http_module modules/mod_proxy_http.so

ProxyPass / http://127.0.0.1:5001/
RequestHeader set X-Forwarded-Proto http
RequestHeader set X-Forwarded-Prefix /

SetEnv proxy-chain-auth On

# auth
<Location />
    AuthName "Registered User"
    AuthType Basic
    AuthUserFile /lib/protected.users
    require valid-user
</Location>
```

Add users by running:

```
sudo htpasswd -c /lib/protected.users [username]
```

Some apps will support basic auth in the URL like http://[username]:[pass]@my.domain.com

## Ubuntu Service

Add a service file to /etc/systemd/system/podly.service

```
[Unit]
Description=Podly Podcast Service
After=network.target

[Service]
User=yourusername
Group=yourusername
WorkingDirectory=/path/to/your/app
ExecStart=/usr/bin/pipenv run python src/main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

enable the service

```
sudo systemctl daemon-reload
sudo systemctl enable podly.service
```

## Database Update

The database should automatically configure & upgrade on launch.

After data model change run:

```
pipenv run flask --app ./src/main.py db migrate -m "[change description]"
```

On next launch the database should update.

## Docker Support

Podly can be run in Docker with support for both NVIDIA GPU and non-NVIDIA environments. Use Docker if you prefer containerized deployment or need GPU acceleration.

### Quick Start with Docker

1. Set up your configuration:

   ```bash
   cp config/config.yml.example config/config.yml
   # Edit config.yml with your settings
   ```

2. Run Podly with Docker:

   ```bash
   # Make the script executable first
   chmod +x run_podly_docker.sh
   ./run_podly_docker.sh
   ```

   This will automatically detect if you have an NVIDIA GPU and use it for acceleration.

### Docker vs Native

- **Use Docker** (`./run_podly_docker.sh`) if you:

  - Want containerized deployment
  - Need GPU acceleration for Whisper
  - Prefer isolated environments

- **Use Native** (`./run_podly.sh`) if you:
  - Want faster development iteration
  - Prefer direct access to logs and debugging
  - Don't need GPU acceleration

### Docker Setup Troubleshooting

If you experience Docker build issues, try the test build option to validate your setup:

```bash
./run_podly_docker.sh --test-build
```

### Docker Options

You can use these command-line options with the run script:

```bash
# Development mode - rebuild containers before starting (use after code changes)
./run_podly_docker.sh --dev

# Production mode - use published Docker images from GitHub Container Registry
./run_podly_docker.sh --production

# Lite mode - smaller image without Whisper (remote transcription only)
./run_podly_docker.sh --lite

# Force CPU mode even if GPU is available
./run_podly_docker.sh --cpu

# Force GPU mode (will fail if no GPU is available)
./run_podly_docker.sh --gpu

# Only build the Docker image without starting containers
./run_podly_docker.sh --build

# Test if the Docker build works (helpful for troubleshooting)
./run_podly_docker.sh --test-build

# Run in background/detached mode
./run_podly_docker.sh -d
```

### Development vs Production Modes

**Development Mode** (default):

- Uses local Docker builds
- Requires rebuilding after code changes: `./run_podly_docker.sh --dev`
- Mounts essential directories (config, input/output, database) and live code for development
- Good for: development, testing, customization

**Production Mode**:

- Uses pre-built images from GitHub Container Registry
- No building required - images are pulled automatically
- Same volume mounts as development
- Good for: deployment, quick setup, consistent environments

```bash
# Start with existing local container
./run_podly_docker.sh

# Rebuild and start after making code changes
./run_podly_docker.sh --dev

# Use published images (no local building required)
./run_podly_docker.sh --production
```

### Docker Environment Configuration

The Docker setup uses runtime environment variables that can be configured when starting the container:

**Environment Variables**:

- `PUID`/`PGID`: User/group IDs for file permissions (automatically set by run script)
- `CUDA_VISIBLE_DEVICES`: GPU device selection for CUDA acceleration
- `CORS_ORIGINS`: Backend CORS configuration (defaults to accept requests from any origin)

## FAQ

Q: What does "whitelisted" mean in the UI?

A: It means an episode is eligible for download and ad removal. By default, new episodes are automatically whitelisted (`automatically_whitelist_new_episodes`), and only a limited number of old episodes are auto-whitelisted (`number_of_episodes_to_whitelist_from_archive_of_new_feed`). This helps control costs by limiting how many episodes are processed. You can adjust these settings in your config.yml for more manual control.

Q: How can I enable whisper GPU acceleration?

A: There are two ways to enable GPU acceleration:

1. **Using Docker**:

   - Use the provided Docker setup with `run_podly_docker.sh` which automatically detects and uses NVIDIA GPUs if available
   - You can force GPU mode with `./run_podly_docker.sh --gpu` or force CPU mode with `./run_podly_docker.sh --cpu`

2. **In a local environment**:
   - Install the CUDA version of PyTorch to your virtual environment:
   ```bash
   pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
   ```

## Contributing

We welcome contributions to Podly! Here's how you can help:

### Development Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/yourusername/podly.git
   ```
3. Create a new branch for your feature:
   ```bash
   git checkout -b feature/your-feature-name
   ```

#### Application Ports

Both local and Docker deployments provide a consistent experience:

- **Application**: Runs on port 5001 (configurable via `config.yml`)
  - Serves both the web interface and API endpoints
  - Frontend is built as static assets and served by the backend
- **Development**: Both `run_podly.sh` and `run_podly_docker.sh` serve everything on port 5001
  - Local script builds frontend to static assets (like Docker)
  - Restart `./run_podly.sh` after frontend changes to rebuild assets

#### Development Modes

Both scripts provide equivalent core functionality with some unique features:

**Common Options (work in both scripts)**:

- `-b/--background` or `-d/--detach`: Run in background mode
- `-h/--help`: Show help information

**Local Development** (`./run_podly.sh`):

- **Development mode**: `./run_podly.sh` - always builds frontend fresh, restart after frontend changes
- Focused on local development only (use Docker script for production)

**Docker Development** (`./run_podly_docker.sh`):

- **Development mode**: `./run_podly_docker.sh --dev` - rebuilds containers with code changes
- **Production mode**: `./run_podly_docker.sh --production` - uses pre-built images
- **Docker-specific options**: `--build`, `--test-build`, `--gpu`, `--cpu`, `--cuda=VERSION`, `--rocm=VERSION`, `--branch=BRANCH`

**Functional Equivalence**:
Both scripts provide the same core user experience:

- Application runs on port 5001 (configurable)
- Frontend served as static assets by Flask backend
- Same web interface and API endpoints
- Compatible background/detached modes

### Running Tests

Before submitting a pull request, you can run the same tests that run in CI:

To prep your pipenv environment to run this script, you will need to first run:

```bash
pipenv install --dev
```

Then, to run the checks,

```bash
scripts/ci.sh
```

This will run all the necessary checks including:

- Type checking with mypy
- Code formatting checks
- Unit tests
- Linting

### Pull Request Process

1. Ensure all tests pass locally
2. Update the documentation if needed
3. Create a Pull Request with a clear description of the changes
4. Link any related issues

### Code Style

- We use black for code formatting
- Type hints are required for all new code
- Follow existing patterns in the codebase
