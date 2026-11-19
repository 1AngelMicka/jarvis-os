English | [Français](README.fr.md)

# JARVIS 2

A local-first personal assistant: long-term memory, streaming conversation with the AI of your choice, and a HUD interface, with nothing irreversible or external done without your approval.

[![CI](https://github.com/1AngelMicka/jarvis-os/actions/workflows/ci.yml/badge.svg)](https://github.com/1AngelMicka/jarvis-os/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/github/v/tag/1AngelMicka/jarvis-os?sort=semver&label=version)](https://github.com/1AngelMicka/jarvis-os/tags)

## Install

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/1AngelMicka/jarvis-os/main/install.ps1 | iex
```

macOS, Linux:

```sh
curl -LsSf https://raw.githubusercontent.com/1AngelMicka/jarvis-os/main/install.sh | sh -s --
```

No Docker, no Node. Details and options [below](#installation-details) and in [docs/INSTALLATION.md](docs/INSTALLATION.md); if something goes wrong: [docs/DEPANNAGE.md](docs/DEPANNAGE.md).

> **Status: in development (0.8.0).** Phases 1 to 10 and 13 of the plan are done (foundation, dialogue, memory, security, AI connectors, installation, agents, memory v2, Claude Code workshops, voice and vision, every capability of JARVIS v1); phase 14 is nearly complete. The desktop app and its installers are built by GitHub Actions and are not signed yet; encrypted backup is ready. The interface is available in French and English (the main screens; a few advanced views are still French only).

## Screenshots

<!-- Images to be provided: docs/images/demo.gif, docs/images/theme-*.png (one per theme), docs/images/mobile.png. They are not in the repository yet. -->

- [Demo (GIF)](docs/images/demo.gif)
- Themes: [JARVIS](docs/images/theme-jarvis.png) · [Studio nocturne](docs/images/theme-studio.png) · [Atelier clair](docs/images/theme-atelier.png) · [Console épurée](docs/images/theme-console.png) · [Présence](docs/images/theme-presence.png)
- [On a phone](docs/images/mobile.png)

## What JARVIS 2 does

**Conversation with the AI of your choice**
- Streaming replies, stored history, titles and dated summaries of each conversation.
- Connectors: your accounts through the providers' official programs (Claude Code, OpenAI Codex, Google Antigravity with a warning), your API keys (Anthropic, OpenAI, Gemini, OpenRouter, any OpenAI-compatible service), your local models (Ollama, LM Studio, llama.cpp, vLLM).
- Task-type router (code, reasoning, quick, private) by a local classifier, each route scored on real measurements and demoted when it fails; a private route never goes to an external AI.
- Automatic router, and a multi-AI council: several connectors answer in parallel, then one writes the synthesis.
- Costs per connector (day, month), spending caps, Claude Code subscription gauges; each reply shows the engine that answered.

**Memory**
- Long-term memory with hybrid search, editable memory blocks always given to the model, and three privacy levels (public, semi-private, private).
- Nightly consolidation by a **local** AI, forgetting by archiving, deterministic detection of a change of mind (the old fact is replaced), versions and export.
- A recall gate without an LLM decides whether a message needs memory at all.
- Knowledge by domain (concept map, notes, review questions), a guided profile questionnaire, tracked tasks without duplicates.
- Import from JARVIS v1 (read-only).

**Agents and workshops**
- Scheduled recipes, background missions (research with cited web and scientific sources, brainstorm, review) whose report goes into memory.
- MCP tools (persistent sessions) and imported `SKILL.md` skills: unusable until you review them, dangerous capabilities (shell, network, write) blocked until ticked, folder fingerprint checked on every use. Each turn the model is offered fewer than 12 tools, chosen by meaning.
- Claude Code workshops: each one works in its own git worktree and branch, and JARVIS decides on every tool it asks to use; pause, resume, close.
- Read-only watch of your own Claude Code sessions.
- Continuous improvement: a suggestion becomes a workshop, then a tested preview, then a deployment request you approve, with a way back.

**Voice and vision**
- Local transcription (Whisper int8, Silero VAD, hallucination filters, circuit breaker), "Dis Jarvis" wake word in two stages (the second one is a local intent judge), barge-in, end-of-turn detection, global hold-to-talk dictation in the desktop app.
- Owner voice recognition (off by default).
- Text-to-speech: browser voice, Piper (local neural voice) or ElevenLabs (online, with your key).
- Screen or image described on request only, with OCR first.

**Your PC and home**
- Windows PC control: volume, brightness, windows, media, lock, shutdown, power plan, notification banners and dark mode, game mode; live CPU, RAM, GPU and VRAM readings.
- Optional home connectors, off by default: Philips Hue (local bridge API), OBS Studio, and Home Assistant on your local network (🟡 lights, plugs, media; 🔴 locks, alarm, gate, which need your passkey and your recognised voice). See [docs/HOME_ASSISTANT.md](docs/HOME_ASSISTANT.md).
- Wyoming server: JARVIS's transcription and voice offered to Home Assistant and to voice satellites in each room (one key per device, only audio after the wake word, per-room presence, volume caps, per-person profiles).
- Quick commands without any AI: a recognised phrase triggers a declared action, editable by you.

**Security**
- Permission levels: 🟢 read (free), 🟡 change (you approve; "always allow" is possible), 🔴 destroy, money, publish, send (explicit confirmation, with a passkey).
- Approval bound to the exact plan shown (SHA-256 fingerprint, checked again right before running) and an undo stack: a reversible action stays undoable for 24 hours.
- Append-only audit log chained with SHA-256 hashes, emergency stop, local vault for API keys, secret and personal-data filter on everything sent to an external provider.
- Per-turn injection barrier (after reading untrusted content, no more actions in that turn) and a detector for replies that claim an action that never happened.
- A "Where does my data go" page generated from your actual configuration (see below).

**Everywhere**
- Phone: installable web app, Web Push notifications, "Share to JARVIS", reachable through Tailscale.
- Desktop app (own window, tray icon, `jarvis://` links), headless home-server mode, morning greeting with weather, sandboxed generated pages, five themes, HUD widgets generated on request (weather, timer, list…) validated against closed lists, never rendered raw, and pinnable.
- Encrypted backup verified by a real restore; SQLite by default, PostgreSQL + pgvector optional.

## Runs locally / What leaves your machine

The in-app page "Où partent mes données" (Where does my data go) builds this map from **your** configuration and shows what is active. Summary of the rules in the code:

| Function | Where | What is sent | When |
|---|---|---|---|
| Memory (storage, embeddings, search) | 🟢 Your PC | Nothing | Always local |
| Dictation, hands-free voice, wake word | 🟢 Your PC | Nothing (Whisper and the intent judge run locally) | Always local |
| Read aloud | 🟢 Your PC | Nothing (browser voice or Piper) | Default |
| Interface | 🟢 Your PC | Nothing: no external font, script or image | Always |
| Local AI (Ollama, LM Studio, llama.cpp, vLLM) | 🟢 Your PC, or 🟡 your network, depending on the address you set | Your messages, only when you write to it | When you use it |
| Screen description | Ollama vision model (your PC by default) | One screenshot per request | Only when you press "Écran" |
| Cloud AI connectors (Claude Code, Codex, Antigravity, Anthropic, OpenAI, Gemini, OpenRouter, declared endpoints) | 🔴 Internet | Your messages and recent history, JARVIS instructions and the memory relevant to the message, titles, summaries, council and missions routed to it; attached images (some connectors ask for a separate consent first); for Claude Code workshops, the code of the projects you opened to workshops | Only connectors you enabled, installed and gave a key to (when one is needed). **Never**: private memories and answers built on them; secrets and personal data are masked before sending |
| Web search (your SearXNG instance) | 🔴 Internet, through the search engines it queries | Mission search queries, never for a private subject | Only if you declared an instance |
| Scientific sources (OpenAlex, arXiv, PubMed, Europe PMC) | 🔴 Internet | Mission search queries, never for a private subject | Research missions; `scientifique = false` turns it off |
| Morning weather (Open-Meteo, no account) | 🔴 Internet | Home coordinates rounded to about 1 km; the city name once, to find them | Only if you chose a location |
| ElevenLabs voice | 🔴 Internet | Text of each sentence read aloud, secrets and personal data masked; sentences on a private subject are read by a local voice | Only with your key and if you chose this voice |
| Model downloads (Hugging Face, public files) | 🔴 Internet | Only the file request (your IP address, as for any download) | Only when you click "Télécharger" |
| Phone through Tailscale | 🟡 Your private network | All phone–PC traffic, end-to-end encrypted; Tailscale only sees your device list | Only if you set up `tailscale serve` |
| Core open to the local network | 🟡 Your network | Exchanges with paired devices (one token per device) | Only if `JARVIS2_OUVERTURE_RESEAU` is set |
| MCP tools | Depends on the program (it may itself reach the Internet) | Parameters of each tool call, after your 🟡 approval | Only servers you declared and enabled |
| Home Assistant | 🟡 Your network (an Internet address is refused) | Actions you approve (target entity and service) and state reads; never your conversations, memory or files, nor the alarm code except to disarm | Only if you enabled and configured it |
| Wyoming server (Home Assistant, voice satellites) | 🟢 Your PC, or 🟡 your network if you choose another address | Transcribed text and JARVIS's voice, sent back only to the device that spoke; audio before the wake word is discarded unread, audio and text are never kept | Only if you turned it on |

Memory privacy levels, towards an external AI:

| Level | Sent to an external AI |
|---|---|
| Public | Everywhere: core memory, blocks, what's new, memories found relevant |
| Semi-private | Only when found relevant to the message |
| Private (`local_uniquement`) | Never: stays on your PC |

In every case, excluded subjects are removed and secrets masked first. Per-call measurements (latency, tokens, cost) stay in your local database; there is no telemetry.

## Hardware

JARVIS 2 runs on Windows, macOS and Linux (PC control is Windows only). `jarvis2 materiel` shows what it detects and the models it suggests; it is read-only and installs, downloads and starts nothing.

**Without a GPU, or without any local model**: everything works with a cloud connector or your Claude Code subscription. Memory (embeddings) runs on the CPU in any case, and transcription falls back to the CPU; local conversation models then run on the CPU too, slowly, capped at the 7–9 billion parameter tier.

**Detection**: RAM from the system; NVIDIA through `nvidia-smi`; AMD through `rocm-smi`, otherwise the Windows registry or `/sys/class/drm` on Linux; Apple Silicon (unified memory, Metal); Intel graphics through Vulkan. Below 4 GB of VRAM (integrated graphics), the card is ignored and the CPU is used.

**AMD**: cards supported by ROCm (Radeon RX 6800 and above, RX 7000, RX 9000, Radeon Pro W6800 / W7000, Instinct) use ROCm; other AMD cards use Vulkan, which is experimental in Ollama. For transcription, an AMD card is used when the installed CTranslate2 build supports ROCm; otherwise Whisper runs on the CPU. Nothing assumes an NVIDIA card.

**How a model is suggested**: usable memory is the card's VRAM (with GPU acceleration and at least 4 GB), 70 % of unified memory on Apple Silicon, or otherwise half the RAM. JARVIS takes the largest tier that fits, then goes **one tier down** to keep room for long context and other programs; the maximum is shown for reference.

| Use | Memory needed (4-bit quantisation, context included) → size, suggested model |
|---|---|
| Conversation (Ollama) | 3 GB → 1–2B `qwen3.5:2b` · 5 GB → 3–4B `qwen3.5:4b` · 8 GB → 7–9B `qwen3.5:9b` · 11 GB → 12–14B `gemma4:12b` · 21 GB → 24–32B `qwen3.5:27b` · 44 GB → 70B `llama3.3:70b` |
| Vision (Ollama) | 3 GB → 2B `qwen3.5:2b` · 8 GB → 7B `qwen2.5vl:7b` · 22 GB → 32B `qwen2.5vl:32b` (on CPU: 2B at most) |
| Memory embeddings (RAM, CPU) | 2 GB → multilingual MiniLM, 384 dimensions (default, about 220 MB downloaded once) · 8 GB → `BAAI/bge-m3` |
| Transcription, Whisper (RAM) | 2 GB → tiny · 4 GB → base · 8 GB → small · 16 GB → medium · 32 GB → large-v3 |

Model names are examples to check in the Ollama catalogue. Ollama is never started automatically: the install script only offers it (box unchecked by default), and JARVIS starts it only on your explicit request and stops only the Ollama it started.

## How it compares

JARVIS 2 takes ideas from several personal-assistant projects. **None is installed or required**: each idea kept is reimplemented, and code is reused only from projects with a permissive licence, credited in [NOTICE](NOTICE). The table lists what JARVIS 2 takes from each one and whether it is built in the code today; what is not yet built is on the [plan](docs/PLAN.md). Full list and licences: [docs/INSPIRATIONS.md](docs/INSPIRATIONS.md).

| Project | Licence | What JARVIS 2 takes from it | Status |
|---|---|---|---|
| OpenJarvis | Apache-2.0 | Installer resume and a single hardware → model table; subscription gauges and reply footer; skills with trust and confinement; extended secret masking, privacy levels, recall gate (ideas, reimplemented); install presets | Built |
| TopMyster/jarvis | MIT | pipx entry point | Built |
| ASDprogrammer521/jarvis | MIT | Per-turn injection barrier, approval bound to the exact plan, undo stack; PC control and modes that really change Windows | Built |
| lancejames221b/jarvis | MIT | Follow-up without wake word, active / standby states; owner voice recognition, closed for 🟡🔴 when unavailable | Built |
| akshayaggarwal99/jarvis | MIT | Robust transcription; global dictation on Windows | Built |
| sosoj92/jarvis | MIT | French hallucination filter; "always allow" for 🟡, never 🔴 remotely without a key | Built |
| b1-loop | MIT | Barge-in; step-by-step latency measurement | Built |
| microsoft/JARVIS (HuggingGPT) | MIT | Brainstorm → spec → plan → execution; missions as a graph | In part: brainstorm missions; spec → plan → execution and the mission graph are planned |
| DonJyde/jarvis | MIT | Filtered generated widgets | Built |
| livekit-rtc | Apache-2.0 | Echo cancellation (possible dependency) | Built, when the optional `livekit` package is installed |
| Dodaios | Apache-2.0 | End of turn, early transcription (idea) | Built |
| isair/jarvis | Non-commercial | Two-stage wake word (idea only) | Built |
| NeyorDEV/jarvis | GPL | Persistent MCP, tools chosen by meaning (idea only) | Built |
| amanimran786/jarvis-ai | AGPL | Workshops in a real sandbox (taken the other way round: refuse when unavailable) | Done (container without network, Windows Sandbox, bubblewrap, sandbox-exec; not yet tried for real) |
| Jarvis.sh | No clear licence | Quick commands without an LLM (idea only, without `eval`) | Built |
| jarvis799 | No clear licence | Actions verified by re-reading the state (idea only) | Built (PC settings are read back) |
| hasibjaan | No clear licence | HUD separated from the audio thread (idea only) | Built (Présence theme) |

JARVIS 2's own focus: local first, your own accounts through the providers' official programs, permissions and audit built before any access is given, and a data-flow map generated from the real configuration.

## Installation details

The one-line commands above fetch the script from this repository; by default it installs the latest release. With a local wheel:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 --source <jarvis2-x.y.z-py3-none-any.whl>
```

```sh
sh install.sh --source <jarvis2-x.y.z-py3-none-any.whl>
```

The script installs what is missing (uv, through winget on Windows and Homebrew on macOS when present, otherwise Astral's official script, after confirmation), then JARVIS 2 (`uv tool install`, Python 3.13 managed by uv), adds the `jarvis2` command to the PATH (on Windows, the session PATH is re-read from the registry: no need to reopen the terminal), prepares the SQLite database and the embeddings model (about 220 MB, once), and starts `jarvis2`: the interface opens in the browser at `http://localhost:8765`.

- **Ollama and a first model** are only **offered**, through a checkbox unchecked by default; the model is chosen for your PC by the hardware → model table (`jarvis2 materiel`). Without anyone to answer (CI, `--oui`), nothing is checked. The script never starts Ollama.
- **Resume**: each step is recorded in `installation.etat` (configuration folder); after an interruption, running the script again resumes where it stopped (`--recommencer` to redo everything).
- **Honest summary** at the end: what was done, refused, failed, and what remains to do.
- Options shared by both scripts: `--oui` (ask nothing), `--avec-ollama` / `--sans-ollama`, `--essai` (dry run: shows what would be done, runs nothing), `--sans-demarrer`, `--sans-modifier-path`, `--recommencer`. Exit codes: 0 installed, 1 a step failed (running again resumes), 2 invalid option, 3 required tool refused.

With [pipx](https://pipx.pypa.io) instead of the scripts (same wheel, interface included):

```sh
pipx install --python 3.13 jarvis2-x.y.z-py3-none-any.whl
jarvis2 docteur --reparer   # SQLite database and embeddings model, once
jarvis2
```

On first launch, the PC's browser pairs in one click, then the **setup assistant** checks everything (with "Réparer" buttons), helps you choose an AI and pair your phone. It stays available from the Status panel ("Installation").

Useful commands: `jarvis2` (start and open the interface), `jarvis2 docteur` (diagnosis; `--json`, `--reparer`), `jarvis2 materiel` (PC hardware and suggested models, read-only), `jarvis2 jumeler` (pairing link for a device), `jarvis2 verifier-audit`, `jarvis2 lever-urgence` (recovery if the passkey is lost), `jarvis2 serveur --sans-ecran` (headless home server: see [docs/SERVEUR.md](docs/SERVEUR.md)).

Optional, detected but never installed by JARVIS:

- [Claude Code](https://code.claude.com), signed in to **your** account (`claude /login`), to use your Claude subscription. A warning (personal use) must be read and ticked once.
- [Ollama](https://ollama.com) for local models (the install script offers it, unchecked; JARVIS itself never installs or starts it on its own).
- [Tailscale](https://tailscale.com/download) for the phone (see below).

## Desktop app

The installers (Windows `.exe`/`.msi`, macOS `.dmg`, Linux `.deb`/`.AppImage`) are attached to each published release. The app opens the interface in its own window, starts the Core if it is not running, and sits in the notification area (Ctrl+Shift+J, or Ctrl+Alt+J if the first is taken, brings it back). It relies on the Core installed by the script above.

The installers are not signed yet:

- **Windows**: SmartScreen shows "Windows protected your PC". Click "More info", then "Run anyway".
- **macOS**: Gatekeeper refuses to open the app. After copying it to Applications, run once `xattr -dr com.apple.quarantine "/Applications/JARVIS 2.app"`.

Only download the installers from this repository's releases page.

## Backup

```powershell
jarvis2 sauvegarde creer --dossier D:\Backups\JARVIS      # encrypted with your passphrase; keep it off the PC
jarvis2 sauvegarde verifier --fichier D:\Backups\JARVIS\jarvis2-YYYYMMDD-HHMMSS.jarvis2
```

Verification restores the backup into a temporary database and checks the rows and the audit chain. Without the passphrase, the backup is unreadable: write it down somewhere other than this PC.

## Phone

JARVIS only listens on the PC. To reach it from your phone, even away from home:

1. Install Tailscale on the PC and the phone, with the same account.
2. On the PC, once: `tailscale serve --bg 8765`. JARVIS is then reachable at `https://<pc-name>.<network>.ts.net`, on your private network only.
3. In the setup assistant (Phone step) or the Security tab: "Associer un téléphone" (pair a phone), then scan the QR code. On the phone, "Add to Home Screen" installs JARVIS as an app.

## Storage

By default, an SQLite file in the data folder (`%LOCALAPPDATA%\JARVIS2` or `~/.local/share/jarvis2`, movable with `JARVIS2_DOSSIER_DONNEES`). PostgreSQL + pgvector remains possible (`JARVIS2_STOCKAGE=postgres`, see `docker-compose.yml`). To switch: `jarvis2 stockage copier --vers sqlite` (or `--vers postgres`), into an empty store; the copy is verified (row counts, audit chain).

Personal configuration (excluded subjects, import exclusions, connectors, prices): copy `config.exemple.toml` to `%APPDATA%\JARVIS2\config.toml` (Windows) or `~/.config/jarvis2/config.toml`. Core settings (port, storage…): `.env.example`.

## Importing data

From JARVIS v1 (`pg_dump -Fc` backup, PostgreSQL storage): see [docs/DECISIONS.md](docs/DECISIONS.md#imports--sources-génériques-lecture-seule-exclusions-locales), then `jarvis2 stockage copier --vers sqlite` if you want to move to SQLite.

## AI accounts and provider terms

JARVIS is not affiliated with any AI provider. With an account (rather than an API key), it calls the provider's **official program**, installed and signed in by you, without modifying it, and never reads your credentials. Your use remains subject to each provider's terms:

- **Claude Code** (Claude subscription): personal subscription, for your own use, no commercial use or use for other people. The warning must be ticked once.
- **OpenAI Codex** (ChatGPT account): according to OpenAI's terms.
- **Google Antigravity**: its terms forbid access through third-party software and accounts have been suspended for this use. This connector is off by default, carries a permanent "risk" badge, is never chosen automatically, and the Gemini API key is recommended instead.

When in doubt, an API key (billed per use) or a local model is always possible.

## Development

Requirements: [uv](https://docs.astral.sh/uv/), Node 22+ (interface). Docker only for PostgreSQL.

```powershell
cd core; uv sync; uv run python -m jarvis2 serveur   # Core (SQLite by default): http://127.0.0.1:8765
cd interface; npm install; npm run dev                # development interface: http://127.0.0.1:5174
```

With PostgreSQL: `uv run --python 3.13 infra/creer_env.py` (`.env` with generated passwords), `docker compose up -d`, `cd core; uv run python -m jarvis2 migrer`.

To serve the built interface from the Core: `npm run build` in `interface`, then open **http://localhost:8765** (the name `localhost`, not the IP address: passkeys require it). To build the installable package: `npm run build`, then `cd core; uv build --wheel` (the interface is included in the wheel; without a built interface, the wheel is built without it, with a warning, and the Core shows an explanation page). To install straight from the repository: `pipx install --python 3.13 ./core` after `npm run build`.

Checks:

```powershell
cd core; uv run pytest; uv run ruff check .; uv run mypy   # tests on SQLite, and on PostgreSQL if Docker is running
cd interface; npm run verifier
```

Code comments, documentation and commit messages are in French. Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Documentation

- [Installation](docs/INSTALLATION.md) · [Troubleshooting](docs/DEPANNAGE.md) · [FAQ](docs/FAQ.md)
- [Architecture](docs/ARCHITECTURE.md) · [Security and permissions](docs/SECURITE.md) · [Writing a skill, command or recipe](docs/EXTENSIONS.md) · [Home server](docs/SERVEUR.md) · [Home Assistant and satellites](docs/HOME_ASSISTANT.md)
- [Roadmap](docs/FEUILLE_DE_ROUTE.md) · [Plan](docs/PLAN.md) · [Decisions](docs/DECISIONS.md) · [Inspirations](docs/INSPIRATIONS.md) · [Interface design](interface/DESIGN.md)
- [Changelog](CHANGELOG.md) · [Reporting a vulnerability](SECURITY.md)

## License

[Apache 2.0](LICENSE). Third-party notices: [NOTICE](NOTICE).
