# AI Team Leader ViciBox

## Status: ✅ WORKING + Conformity Check Added

## What it does
- **Monitor** (every minute): Checks idle agents, hopper levels, answers questions
- **Conformity Check** (4x daily): Transcribes recordings, checks call structure

## Components

### 1. Monitor (`ai-team-leader-monitor`)
- Runs every minute via cron
- Alerts idle agents (>5 min)
- Checks hopper levels (<20 leads)
- Answers agent questions via ViciBox chat
- Uses NVIDIA NIM AI (GLM-5)

### 2. Conformity Check (`ai-team-leader-conformity`)
- Runs 4x daily during office hours
- **Schedule**: 10h, 14h, 18h, 22h CET (Mon-Fri)
- **Covers**: France (10h-20h) + Canada (9h-19h Montreal)
- Uses faster-whisper for transcription
- Checks call structure (greeting → pitch → handling → closing)
- Checks campaign-specific keywords
- AI quality analysis via NVIDIA NIM

## Campaigns Monitored
| ID | Name | Keywords |
|----|------|----------|
| 2002 | Home_energie_combles | isolation, combles, économies, prime |
| 1007 | Prospection_reception_quebec | rendez-vous, réception, québec |
| 2000 | Assur_fatma | assurance, devis, couverture |
| 2001 | Assu_Alexandre | assurance, devis, protection |

## Cron Schedule
```
# Monitor (every minute)
* * * * * /usr/local/bin/ai-team-leader-monitor

# Conformity Check (4x daily, Mon-Fri, office hours)
0 10,14,18,22 * * 1-5 /usr/local/bin/ai-team-leader-conformity
```

## Files
- `src/ai_team_leader.py` - Main monitoring script
- `src/recording_conformity.py` - Conformity check with STT
- `scripts/ai-team-leader-monitor` - Monitor cron wrapper
- `scripts/ai-team-leader-conformity` - Conformity cron wrapper

## Logs
```bash
tail -f /var/log/ai-team-leader.log
```

## GitHub
https://github.com/boubahkarim-png/ai-team-leader-vici

## Next Steps
- [ ] Test conformity check with live recordings
- [ ] Add supervisor notifications for failed conformity
- [ ] Add greeting script integration
