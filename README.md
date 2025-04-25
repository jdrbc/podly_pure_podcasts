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

## Usage

- `config/config.yml.example` into new file `config/config.yml`. Update `llm_api_key` with your key.
- Start the server & note the URL.
  - For example, `192.168.0.2:5001`
- Open 192.168.0.2:5001 in your web browser
- Add podcast RSS feeds to the interface
- Open a podcast app & subscribe to the podly endpoint
  - For example, `http://localhost:5001/feed/1`
- Select an episode & download
- Wait patiently :). Transcription is the slowest part & takes about 1 minute per 15 minutes of podcast on an M3 macbook.

## How To Run

Install ffmpeg

```shell
sudo apt install ffmpeg
```

Copy `config/config.yml.example` into new file `config/config.yml`. Update `llm_api_key` with your key.

```shell
pip install pipenv
pipenv --python 3.11
pipenv install
pipenv shell
python src/main.py
```

## Remote Setup

Podly works out of the box when running locally (see [Usage](#usage)). To run it on a remote server add SERVER to config/config.yml

```
SERVER=http://my.domain.com
```

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

Podly can be run in Docker with support for both NVIDIA GPU and non-NVIDIA environments.

### Quick Start with Docker

1. Set up your configuration:
   ```
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

### Docker Setup Troubleshooting

If you experience Docker build issues, try the test build option to validate your setup:

```bash
./run_podly_docker.sh --test-build
```

### Docker Options

You can use these command-line options with the run script:

```bash
# Force CPU mode even if GPU is available
./run_podly_docker.sh --cpu

# Force GPU mode (will fail if no GPU is available)
./run_podly_docker.sh --gpu

# Only build the Docker image without starting containers
./run_podly_docker.sh --build

# Test if the Docker build works (helpful for troubleshooting)
./run_podly_docker.sh --test-build
```

## FAQ

Q: What does "whitelisted" mean in the UI?

A: It means an episode is eligible for download and ad removal. By default, new episodes are automatically whitelisted (```automatically_whitelist_new_episodes```), and only a limited number of old episodes are auto-whitelisted (```number_of_episodes_to_whitelist_from_archive_of_new_feed```). This helps control costs by limiting how many episodes are processed. You can adjust these settings in your config.yml for more manual control.
  
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
