# AI Team Leader for ViciBox

Lightweight AI-powered supervisor for ViciDial call centers.

## Features

- **Agent Monitoring**: Alerts idle agents via ViciBox chat
- **Hopper Alerts**: Notifies when hopper is low
- **AI Responses**: Uses NVIDIA NIM to answer agent questions
- **Minimal Resources**: Runs via cron, no persistent service

## Architecture

```
Cron (every minute) → ai_team_leader.py → MySQL queries → ViciBox Chat
                                              ↓
                                        NVIDIA NIM AI (on-demand)
```

## Resource Usage

| Component | CPU | RAM | Frequency |
|-----------|-----|-----|-----------|
| Monitor script | <5% | ~50MB | 1 min |
| AI response | <10% | ~100MB | On-demand |
| Total impact | Minimal | <150MB peak | On-demand |

**No persistent service** - only runs when triggered by cron.

## Installation

```bash
cd /root/projects/ai-team-leader-vici

# Copy scripts
cp scripts/ai-team-leader-monitor /usr/local/bin/
cp scripts/ai-team-leader-greeting /usr/local/bin/
chmod +x /usr/local/bin/ai-team-leader-*

# Add to crontab
* * * * * /usr/local/bin/ai-team-leader-monitor
```

## Configuration

Edit `config/settings.env`:
- `SUPERVISOR_USER`: Your ViciDial user ID (default: 6666)
- `ACTIVE_CAMPAIGNS`: Campaign IDs to monitor
- `IDLE_ALERT_MINUTES`: Minutes before idle alert
- `HOPPER_LOW_THRESHOLD`: Hopper count threshold

## Components

| File | Purpose |
|------|---------|
| `src/ai_team_leader.py` | Main monitoring script |
| `src/transcriber.py` | Recording transcription (optional) |
| `scripts/ai-team-leader-monitor` | Cron wrapper |
| `scripts/ai-team-leader-greeting` | Agent greeting trigger |

## STT Options

See `docs/STT_OPTIONS.md` for transcription solutions:
- **faster-whisper** (recommended, already installed)
- **Vosk** (configured in AVR)
- **Whisper API Server** (Docker)

## License

MIT
