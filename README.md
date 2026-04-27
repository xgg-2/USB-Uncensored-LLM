# USB-Uncensored-LLM

A portable, air-gapped AI chat system that runs large language models directly from a USB drive or local disk — no internet connection, no cloud, no installation required on the host machine.

> [!note]
> This is a maintained fork of the original project by [techjarves](https://github.com/techjarves/USB-Uncensored-LLM/tree/main).
> The original setup video and concept belong to the original author.
> This fork introduces significant enhancements: a redesigned UI, security hardening, structured logging, preflight checks, central configuration, and improved robustness for redeployment.

**Original project:** [https://github.com/techjarves/USB-Uncensored-LLM](https://github.com/techjarves/USB-Uncensored-LLM/tree/main)
**Original demo video (by techjarves):** [https://youtu.be/60PSXsoXc8A](https://youtu.be/60PSXsoXc8A)

---

## Overview

USB-Uncensored-LLM bundles a lightweight Python HTTP server, a single-file web chat UI, and platform-specific launchers for Windows, macOS, Linux, and Android. You download the AI engine and models once; from then on everything runs fully offline.

The `Shared/` directory is the portable data layer — it holds the engine binaries, model weights, and chat history. Platform folders contain only thin launcher scripts that point into `Shared/`.

---

## Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Python | 3.9+ | 3.12 |
| Storage | 8 GB free | 16 GB+ |
| RAM | 8 GB | 16 GB+ |
| USB speed | USB 3.0 | USB 3.1 / SSD |

For Android: ARM64 device with 6 GB+ RAM, Termux from [F-Droid](https://f-droid.org/en/packages/com.termux/).

---

## Project Structure

```
USB-Uncensored-LLM/
├── Shared/
│   ├── chat_server.py      # Zero-dependency Python HTTP server
│   ├── FastChatUI.html     # Full chat interface (served by chat_server.py)
│   ├── errors.py           # Structured error codes and remedies
│   ├── preflight.py        # Startup checks (disk space, permissions, UI file)
│   ├── bin/                # Engine binaries (downloaded by install script)
│   ├── models/             # GGUF model weights (downloaded by install script)
│   ├── chat_data/          # Chat history and settings (auto-created at runtime)
│   └── logs/               # Rotating server logs (auto-created at runtime)
├── Windows/
│   ├── install.bat         # Downloads engine + models for Windows
│   ├── install-core.ps1    # PowerShell setup logic
│   └── start-fast-chat.bat # Launches engine and opens browser
├── Mac/
│   ├── install.command     # Downloads engine + models for macOS
│   └── start.command       # Launches engine and opens browser
├── Linux/
│   ├── install.sh          # Downloads engine + models for Linux
│   └── start.sh            # Launches engine and opens browser
├── Android/
│   ├── install.sh          # Termux setup (engine + models)
│   └── start.sh            # Launches engine and opens browser in Chrome
├── config.json             # Central configuration (ports, paths, timeouts)
├── VERSION                 # Semantic version string
└── SECURITY.md             # Threat model and known limitations
```

---

## Quick Start

### Step 1 — Install (first time only)

Run the installer for your operating system. It downloads the Ollama engine binary and lets you choose which AI models to install.

| OS | Command |
|----|---------|
| Windows | Double-click `Windows/install.bat` |
| macOS | Run `bash Mac/install.command` in Terminal |
| Linux | Run `bash Linux/install.sh` |
| Android | Run `bash Android/install.sh` in Termux |

> The installer only downloads the engine (~50 MB) and whichever models you select. Models are stored in `Shared/models/` and work across all platforms.

### Step 2 — Launch

| OS | Command |
|----|---------|
| Windows | Double-click `Windows/start-fast-chat.bat` |
| macOS | Run `bash Mac/start.command` |
| Linux | Run `bash Linux/start.sh` |
| Android | Run `bash Android/start.sh` in Termux |

The engine starts in the background and your browser opens the chat UI automatically. The terminal window also prints a LAN IP address so you can access the UI from a phone or tablet on the same network.

---

## Running the Server Directly

If you already have Ollama running separately, you can start just the chat server:

```bash
python Shared/chat_server.py
```

Or without opening a browser:

```bash
python Shared/chat_server.py --no-browser
```

The server reads configuration from `config.json` and binds to port `5000` by default (overridable with the `PORT` environment variable).

---

## Default Ports

| Port | Service |
|------|---------|
| 5000 | Chat web UI (chat_server.py) |
| 11434 | Ollama engine (started by launch scripts) |

---

## Configuration

Edit `config.json` to change defaults:

```json
{
  "ui_port": 5000,
  "ollama_port": 11434,
  "ollama_timeout_seconds": 600,
  "default_model": "",
  "network_bind": "0.0.0.0",
  "encrypt_chat_history": false
}
```

Set `"network_bind": "127.0.0.1"` to restrict access to the local machine only.

---

## AI Models

The installer provides a curated list of uncensored and standard models. You can also place any `.gguf` file manually into `Shared/models/` and it will appear in the model selector.

Recommended models by hardware:

| RAM | Model |
|-----|-------|
| 6-8 GB | Gemma 2 2B (fastest, ~1.6 GB) |
| 10-16 GB | Qwen 9B or similar |
| 16 GB+ | 12B+ parameter models |

---

## LAN Access from Mobile

1. Ensure your phone and the host PC are on the same Wi-Fi network.
2. The terminal shows a Network address (e.g., `http://192.168.1.15:5000`).
3. Open that URL in your mobile browser.

On Windows, allow incoming connections on port `5000` in Windows Firewall if prompted.

---

## Android (Termux)

1. Install Termux from [F-Droid](https://f-droid.org/en/packages/com.termux/) (the Play Store version is outdated).
2. Copy the project folder to your device via USB or `git clone`.
3. Open Termux and navigate to the project folder.
4. Run `bash Android/install.sh` and follow the prompts.
5. Run `bash Android/start.sh` to launch.

Tips for Android:
- Run `termux-wake-lock` before starting to prevent Android from killing the process.
- Keep Termux in the foreground.
- The 2B model is recommended for devices with less than 12 GB RAM.
- Expect 3-10 tokens/second on the 2B model.

---

## Troubleshooting

**The script closes immediately on Windows**
Run it via a Command Prompt window instead of double-clicking, or right-click and choose "Run as Administrator".

**"Engine offline" shown in the UI**
The Ollama engine is not running. Launch via the `start` script for your OS, or start it manually with `Shared/bin/ollama serve`.

**Slow generation speed**
The selected model is too large for available RAM. Switch to the 2B model in the model selector dropdown.

**Port 5000 already in use**
Another process is using the port. Either stop that process or change `"ui_port"` in `config.json`.

---

## Features

### Chat Interface
- Multi-session chat with numbered list and persistent history
- Image and PDF attachment support with drag-and-drop
- Markdown rendering with syntax-highlighted code blocks
- Auto-resizing textarea, Shift+Enter for newlines
- System prompt: set globally or override per conversation

### Conversation Tools
- **Search** — filter all chats by title or message content in real time
- **Rename** — double-click any chat title to edit it inline
- **Export** — download any conversation as Markdown, plain text, or JSON
- **Focus Mode** — hide the sidebar and top bar for distraction-free writing (click the expand icon)
- **Edit & Resend** — hover a user message and click Edit to modify and resend it
- **Regenerate** — hover the last AI response and click Regenerate to get a new answer
- **Generation Stats** — after each response: token count, tokens/second, and elapsed time
- **Model Tag** — each AI response shows which model produced it

### System Monitoring
- Real-time CPU and RAM usage bars in the top bar
- Ollama engine online/offline status with model count
- LAN IP address printed at startup for mobile access

---

## Changes from the Original

This fork diverges from the original [techjarves/USB-Uncensored-LLM](https://github.com/techjarves/USB-Uncensored-LLM/tree/main) in the following areas:

**User Interface**
- Complete UI redesign: terminal-industrial aesthetic, IBM Plex Mono/Sans fonts, muted dark palette
- No emojis, no neon colors, no gradients — clean and professional
- Real vector icons via Lucide (replaced all emoji/text icons)
- Numbered chat list for quick navigation
- Conversation search, inline rename, export modal, focus mode, edit/regenerate, generation stats, per-message model tag

**Security**
- Memory exhaustion protection: hard caps on request body size (8 MB JSON, 64 MB proxy)
- Path traversal fix: `pathlib.is_relative_to()` + extension whitelist for static files
- Ollama proxy path allowlist: only known API endpoints can be proxied
- JSON schema validation on all persisted settings with type coercion and length caps
- `X-Content-Type-Options: nosniff` header on all responses
- Documented threat model in `SECURITY.md`

**Reliability**
- `config.json`: central configuration for all ports, paths, and timeouts
- `Shared/preflight.py`: startup checks for disk space, write permissions, and UI file presence
- `Shared/errors.py`: structured error codes with remedies
- Rotating structured logs (keeps last 5 runs) in `Shared/logs/`
- Graceful shutdown via SIGTERM/SIGINT
- `SO_REUSEADDR` + process cleanup on restart to eliminate "port in use" errors
- `VERSION` file for semantic versioning

---

## Security

See [SECURITY.md](SECURITY.md) for the full threat model, known limitations, and deployment checklist.

---

## Attribution and License

Original concept, installer scripts, and demo video by [techjarves](https://github.com/techjarves).
Original repository: [https://github.com/techjarves/USB-Uncensored-LLM](https://github.com/techjarves/USB-Uncensored-LLM/tree/main)

This project bundles Ollama binaries. See [https://github.com/ollama/ollama](https://github.com/ollama/ollama) for Ollama's license.
All modifications in this fork are released under the MIT License.

---

*This project is built for local computational freedom. Use responsibly.*
