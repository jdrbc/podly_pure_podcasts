# Podly Pure Podcasts

Ad-block for podcasts. Create a private ad-free RSS feed.

Podly will:

- download the requested episode
- transcribe the episode
- have Chat GPT label ad segments
- remove the ad segments
- deliver the ad-free version of the podcast to you

## Usage

- Start the server & note the URL.
  - For example, `192.168.0.2:5001`
  - It'll try to register an mDNS record at `podly.local`
- Open a podcast app & subscribe to a podcast by appending the RSS to the 'rss' endpoint.
  - For example, to subscribe to `https://mypodcast.com/rss.xml`
  - Subscribe to `http://podly.local:5001/rss/https://mypodcast.com/rss.xml`
- Select an episode & download
- Wait patiently :)

## How To Run

Copy `.env.example` into new file `.env`. Update `OPENAI_API_KEY` with your key.

```shell
pipenv --python 3.11
pipenv install
pipenv shell
python src/main.py
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

### Whisper

```shell
WHISPER_MODEL='base.en' # optional
```
