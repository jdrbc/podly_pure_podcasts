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

- `config/config.yml.example` into new file `config/config.yml`. Update `openai_api_key` with your key.
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

Copy `config/config.yml.example` into new file `config/config.yml`. Update `openai_api_key` with your key.

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

## Environment Variables

If you're using OpenAI only the `openai_api_key` is required.

### OpenAI

```shell
openai_api_key='sk-1234567890abcdef1234567890abcdef'
openai_base_url='https://api.openai.com/v1' # optional
openai_model='gpt-4o' # optional
```

### Ollama

```shell
openai_base_url='http://127.0.0.1:11434/v1'
openai_timeout=300
openai_max_tokens=4096
openai_api_key='ollama'
openai_model='phi3:14b-medium-4k-instruct-q5_K_M'
```

### Whisper

```shell
whisper_model='base.en' # optional
```

To use OpenAI API instead of local model

```shell
REMOTE_WHISPER=TRUE # optional
```

## Database Update

The database should automatically configure & upgrade on launch.

After data model change run:

```
pipenv run flask --app ./src/main.py db migrate -m "[change description]"
```

On next launch the database should update.

## FAQ

Q: How can I enable whisper GPU acceleration?

A: You must install the CUDA version of PyTorch to the virtual environment.
  
```pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118```

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

Before submitting a pull request, you can run the same tests that run in CI locally using:

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
