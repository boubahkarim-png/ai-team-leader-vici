# AI Team Leader ViciBox

## Status: ✅ WORKING

## What it does
- Monitors idle agents (alerts after 5 min idle)
- Checks hopper levels (alerts if < 20 leads)
- Answers agent questions via ViciBox manager chat
- Uses NVIDIA NIM AI (GLM-5) for responses
- Runs via cron every minute

## Files
- `src/ai_team_leader.py` - Main Python script
- `scripts/ai-team-leader-monitor` - Cron wrapper
- `config/settings.env.example` - Config template

## Installation
```bash
cd /root/projects/ai-team-leader-vici
cp config/settings.env.example config/settings.env
# Edit config with your NVIDIA_API_KEY
crontab -e  # Add: * * * * * /usr/local/bin/ai-team-leader-monitor
```

## Logs
```bash
tail -f /var/log/ai-team-leader.log
```

## GitHub
https://github.com/boubahkarim-png/ai-team-leader-vici

## Next Steps
- [ ] Add STT transcription (faster-whisper)
- [ ] Add greeting script integration
- [ ] Test with live agents
