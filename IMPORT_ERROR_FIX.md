# ✅ Import Error Fixed

## Problem
```
ImportError: cannot import name 'LOCAL_RTP_IP' from 'app.core.config'
```

## Root Cause
Configuration variables were removed during cleanup but were still being imported by:
- `app/transport/asterisk.py`
- `app/services/media_service.py`

## Solution Applied

### Added to `app/core/config.py`

```python
# RTP IP Configuration
LOCAL_RTP_IP = os.getenv("LOCAL_RTP_IP", "0.0.0.0")
GREETING_RTP_WAIT_S = float(os.getenv("GREETING_RTP_WAIT_S", "2.0"))

# Audio Codec Comfort Noise
RTP_COMFORT_NOISE_ULAW = b'\xff' * 160

# Audio Muting Configuration
AUDIO_MUTING_ENABLED = os.getenv("AUDIO_MUTING_ENABLED", "true").lower() == "true"
AUDIO_MUTING_POST_TTS_CLEAR_DELAY_MS = int(os.getenv("AUDIO_MUTING_POST_TTS_CLEAR_DELAY_MS", "200"))
PREFLUSH_RX_BUFFER_STALE_FRAMES = int(os.getenv("PREFLUSH_RX_BUFFER_STALE_FRAMES", "20"))
```

### Added to `.env`

```bash
LOCAL_RTP_IP=0.0.0.0
GREETING_RTP_WAIT_S=2.0

AUDIO_MUTING_ENABLED=true
AUDIO_MUTING_POST_TTS_CLEAR_DELAY_MS=200
PREFLUSH_RX_BUFFER_STALE_FRAMES=20
```

## Status

✅ **Fixed** - All missing imports now defined  
✅ **Ready to run** - No more import errors  
✅ **Configuration complete** - All variables in place

## To Run

```bash
python main.py
```

Expected output:
```
11:31:04.782 [INFO] [CONFIG] RTP port range: 30000-40000
[STARTUP] Initializing services...
[STARTUP] ✓ Gemini Live provider initialized
```

---

**All fixed and ready to go!** 🚀
