# STT Options for Call Recording Transcription

**Server**: ViciBox v12, 11GB RAM, CPU-only (no GPU)
**Goal**: Transcribe call recordings to extract information

---

## RECOMMENDATION: faster-whisper (INT8)

Already installed: `pip3.11 install faster-whisper` ✅

### Why faster-whisper?
- **4-8x faster** than original Whisper
- **Low memory**: 600MB (base model, INT8)
- **Same accuracy**: Identical to OpenAI Whisper
- **Free & Open Source**: MIT license
- **VAD built-in**: Removes silence automatically

---

## Comparison Table

| Solution | Accuracy | Speed | RAM | Cost |
|----------|----------|-------|-----|------|
| **faster-whisper** ⭐ | Excellent | Fast | 600MB | FREE |
| whisper.cpp | Good | Medium | 500MB | FREE |
| Vosk (in AVR) | Good | Fast | 200MB | FREE |
| OpenAI API | Excellent | N/A | 0 | $0.36/hr |

---

## Quick Usage

```python
from faster_whisper import WhisperModel

model = WhisperModel("base", device="cpu", compute_type="int8")
segments, info = model.transcribe("recording.wav", vad_filter=True)

for seg in segments:
    print(f"[{seg.start:.1f}s] {seg.text}")
```

---

## Model Sizes

| Model | Disk | RAM | Speed | Use Case |
|-------|------|-----|-------|----------|
| tiny | 75MB | 400MB | Fastest | Real-time |
| **base** | 142MB | **600MB** | **Fast** | **Calls** |
| small | 466MB | 1.5GB | Good | High accuracy |
| medium | 1.5GB | 2.2GB | Slow | Multi-language |

**Recommendation**: `base` model - best balance of speed/accuracy.

---

## Vosk (Already in AVR)

Your AVR infrastructure has Vosk pre-configured:

```bash
cd /opt/avr-infra
docker-compose -f docker-compose-vosk.yml up -d avr-asr-vosk
```

API: `http://avr-asr-vosk:6010/speech-to-text-stream`

---

## Docker API Server (Optional)

```bash
docker run -d -p 9000:9000 \
  -e ASR_MODEL=base \
  -e ASR_ENGINE=faster_whisper \
  onerahmet/openai-whisper-asr-webservice:latest

curl -X POST "http://localhost:9000/asr" -F "audio_file=@rec.wav"
```

---

## Recording Location

ViciDial recordings: `/var/spool/asterisk/monitorDONE/`

Format: `YYYYMMDD-HHMMSS_PHONE_CAMPAIGN-in.wav`

---

## Integration Workflow

1. **Detect**: New recording in `monitorDONE/`
2. **Transcribe**: `faster-whisper` → text
3. **Extract**: NVIDIA NIM AI → email, address
4. **Store**: Update lead comments or database

---

## Free API Tiers (Limited)

| Service | Free Tier |
|---------|-----------|
| Google STT | 60 min/month |
| Azure Speech | 5 hrs/month |
| AssemblyAI | $50 credit |

**Verdict**: Self-hosted is better - unlimited, private, free.

---

*Updated: 2026-04-15*
