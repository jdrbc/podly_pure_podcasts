# How To Run: Ultimate Beginner's Guide

This guide will walk you through setting up Podly from scratch, even if you've never used Docker before. Podly creates ad-free RSS feeds for podcasts by automatically detecting and removing advertisement segments.

## Highly Recommend!

Want an expert to guide you through the setup? Download an AI powered IDE like cursor https://www.cursor.com/ or windsurf https://windsurf.com/

Most IDEs have a free tier you can use to get started. Alternatively, you can use your own [LLM API key in Cursor](https://docs.cursor.com/settings/api-keys) (you'll need a key for Podly anyways). 

Open the AI chat in the IDE. Enable 'Agent' mode if available, which will allow the IDE to help you run commands, view the output, and debug or take corrective steps if necessary.

Paste the one of the prompts below into the chat box.

If you don't have the repo downloaded:
```
Help me install git, and run podly https://github.com/jdrbc/podly_pure_podcasts 
After the project is cloned, follow the 'podly_pure_podcasts/docs/how_to_run_beginners.md' guide to run podly. Briefly, help me:
- install docker & docker compose
- get an OpenAI API key, and configure config/config.yml
- run the `./run-podly-docker.sh --build` and then `./run-podly-docker.sh -d` scripts
Be sure to check if a dependency is already installed before downloading.
We recommend docker because installing ffmpeg & local whisper can be difficult.
The docker image have both ffmpeg & local whisper preconfigured.
Help me setup config/config.yml
Podly works with many different LLMs, it does not require an open-ai key.
Check your work by retrieving the index page from localhost:5001 at the end.
```

If you do have the repo pulled, open this file and prompt:
```
Review this project, follow this guide and start podly on my computer. 
Briefly, help me:
- install docker & docker compose
- get an OpenAI API key, and configure config/config.yml
- run the `./run-podly-docker.sh --build` and then `./run-podly-docker.sh -d` scripts
Be sure to check if a dependency is already installed before downloading.
We recommend docker because installing ffmpeg & local whisper can be difficult.
The docker image have both ffmpeg & local whisper preconfigured.
Podly works with many different LLMs, it does not need to work with open-ai.
Check your work by retrieving the index page at the end.
```

Follow along as the agent sets up Podly for you!

## Prerequisites

### 1. Install Docker and Docker Compose

#### On Windows:
1. Download and install [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/)
2. During installation, make sure "Use WSL 2 instead of Hyper-V" is checked
3. Restart your computer when prompted
4. Open Docker Desktop and wait for it to start completely

#### On macOS:
1. Download and install [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/)
2. Drag Docker to your Applications folder
3. Launch Docker Desktop from Applications
4. Follow the setup assistant

#### On Linux (Ubuntu/Debian):
```bash
# Update package index
sudo apt update

# Install Docker
sudo apt install docker.io docker-compose-v2

# Add your user to the docker group
sudo usermod -aG docker $USER

# Log out and log back in for group changes to take effect
```

#### Verify Installation:
Open a terminal/command prompt and run:
```bash
docker --version
docker compose version
```

You should see version information for both commands.

### 2. Get an OpenAI API Key

1. Go to [OpenAI's API platform](https://platform.openai.com/)
2. Sign up for an account or log in if you already have one
3. Navigate to the [API Keys section](https://platform.openai.com/api-keys)
4. Click "Create new secret key"
5. Give it a name (e.g., "Podly")
6. **Important**: Copy the key immediately and save it somewhere safe - you won't be able to see it again!
7. Your API key will look something like: `sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

> **Note**: OpenAI API usage requires payment. Make sure to set up billing and usage limits in your OpenAI account to avoid unexpected charges.

## Setup Podly

### 1. Download the Project

```bash
git clone https://github.com/normand1/podly_pure_podcasts.git
cd podly_pure_podcasts
```

### 2. Configure the Application

1. Navigate to the `config` folder in your Podly directory
2. Find the file named `config.yml.example`
3. **Copy** this file and rename the copy to `config.yml`
   - On Windows: Right-click → Copy, then right-click → Paste, rename to `config.yml`
   - On macOS/Linux: `cp config.yml.example config.yml`

4. Open `config.yml` in a text editor (Notepad, TextEdit, VS Code, etc.)
5. Find the line that says:
   ```yaml
   llm_api_key: sk-proj-XXXXXXXXXXXXXXXXXXXXXXXX
   ```
6. Replace `sk-proj-XXXXXXXXXXXXXXXXXXXXXXXX` with your actual OpenAI API key
7. Save the file

> **Important**: Keep your API key secure! Never share it publicly or commit it to version control.

## Running Podly

### 1. Open Terminal/Command Prompt

Navigate to your Podly directory:
```bash
cd path/to/your/podly_pure_podcasts
```

### 2. Run the Application

Podly includes a convenient script that handles all the Docker complexity for you:

**For most users (auto-detects GPU if available):**
```bash
./run_podly_docker.sh --build
./run_podly_docker.sh # to easily view logs and debug issues
./run_podly_docker.sh -d # to run in background so you don't need to leave a terminal window open
```

**On Windows, if the above doesn't work:**
```cmd
bash run_podly_docker.sh --build
bash run_podly_docker.sh
```

### 3. First Run

The first time you run Podly:
1. Docker will download and build the necessary images (this may take 5-15 minutes)
2. You'll see lots of text scrolling by - this is normal!
3. Look for a message like: "Running on http://0.0.0.0:5001"
4. The application is now ready!

### 4. Access the Web Interface

1. Open your web browser
2. Go to: `http://localhost:5001`
3. You should see the Podly web interface

## Advanced Options

The run script supports several options:

```bash
# Force CPU-only processing (if you have GPU issues)
./run_podly_docker.sh --cpu

# Force GPU processing
./run_podly_docker.sh --gpu

# Just build the container without running
./run_podly_docker.sh --build

# Test build from scratch (useful for troubleshooting)
./run_podly_docker.sh --test-build
```

## Using Podly

### Adding Your First Podcast

1. In the web interface, look for an "Add Podcast" or similar button
2. Paste the RSS feed URL of your podcast
3. Podly will start processing new episodes automatically
4. Processed episodes will have advertisements removed

### Getting Your Ad-Free RSS Feed

1. After adding a podcast, Podly will generate a new RSS feed URL
2. Use this new URL in your podcast app instead of the original
3. Your podcast app will now download ad-free versions!

## Troubleshooting

### "Docker command not found"
- Make sure Docker Desktop is running
- On Windows, restart your terminal after installing Docker
- On Linux, make sure you logged out and back in after adding yourself to the docker group

### Cannot connect to the Docker daemon. Is the docker daemon running?

- If using docker desktop, open up the app, otherwise start the daemon

### "Permission denied" errors
- On macOS/Linux, make sure the script is executable: `chmod +x run_podly_docker.sh`
- On Windows, try running Command Prompt as Administrator

### OpenAI API errors
- Double-check your API key is correct in `config.yml`
- Make sure you have billing set up in your OpenAI account
- Check your usage limits haven't been exceeded

### Port 5001 already in use
- Another application is using port 5001
- Either stop that application or modify the port in `compose.yml`

### Out of memory errors
- Close other applications to free up RAM
- Consider using `--cpu` flag if you have limited memory

## Stopping Podly

To stop the application:
1. In the terminal where Podly is running, press `Ctrl+C`
2. Wait for the containers to stop gracefully

## Getting Help

If you encounter issues ask in our discord, we're friendly!

https://discord.gg/FRB98GtF6N

## What's Next?

Once you have Podly running:
- Explore the web interface to add more podcasts
- Check the configuration file for advanced settings
- Consider setting up automatic background processing
- Enjoy your ad-free podcasts!
