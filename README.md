# Podly Pure Podcasts

Ad-block for podcasts. Create a private ad-free RSS feed.

Podly will:

- download the requested episode
- transcribe the episode
- have Chat GPT label ad segments
- remove the ad segments
- deliver the ad-free version of the podcast to you

## Usage

- `.env.example` into new file `.env`. Update `OPENAI_API_KEY` with your key.
- Start the server & note the URL.
  - For example, `192.168.0.2:5001`
- Open a podcast app & subscribe to a podcast by appending the RSS to the podly endpoint.
  - For example, to subscribe to `https://mypodcast.com/rss.xml`
  - Subscribe to `http://192.168.0.2:5001:5001/https://mypodcast.com/rss.xml`
- Select an episode & download
- Wait patiently :). Transcription is the slowest part & takes about 1 minute per 15 minutes of podcast on an M3 macbook.

## How To Run

Install ffmpeg

```shell
sudo apt install ffmpeg
```

Copy `.env.example` into new file `.env`. Update `OPENAI_API_KEY` with your key.

```shell
pip install pipenv
pipenv --python 3.11
pipenv install
pipenv shell
python src/main.py
```

## Remote Setup

Podly works out of the box when running locally (see [Usage](#usage)). To run it on a remote server add SERVER to .env

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

If you're using OpenAI only the `OPENAI_API_KEY` is required.

### OpenAI

```shell
OPENAI_API_KEY='sk-1234567890abcdef1234567890abcdef'
OPENAI_API_BASE='https://api.openai.com/v1' # optional
OPENAI_MODEL='gpt-4o' # optional
```

### Ollama

```shell
OPENAI_API_BASE='http://127.0.0.1:11434/v1'
OPENAI_TIMEOUT=300
OPENAI_MAX_TOKENS=4096
OPENAI_API_KEY='ollama'
OPENAI_MODEL='phi3:14b-medium-4k-instruct-q5_K_M'
```
