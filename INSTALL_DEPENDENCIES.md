# ⚠️ INSTALL MISSING DEPENDENCIES

## Error
```
[ERROR] [Gemini Live] google-generativeai not installed
[ERROR] [Gemini Live] Install: pip install google-generativeai websockets
```

## Solution

### On Production Server (/opt/IndiaMart)

**Step 1: Activate virtual environment**
```bash
source /opt/IndiaMart/venv/bin/activate
```

**Step 2: Install required packages**
```bash
pip install google-generativeai>=0.4.0 websockets>=11.0
```

**Or install all requirements from file:**
```bash
pip install -r requirements_gemini.txt
```

**Step 3: Verify installation**
```bash
python -c "import google.generativeai; import websockets; print('✅ All dependencies installed')"
```

Expected output:
```
✅ All dependencies installed
```

**Step 4: Restart application**
```bash
cd /opt/IndiaMart
python main.py
```

---

## What These Packages Do

### `google-generativeai` (>=0.4.0)
- Python SDK for Google's Generative AI (Gemini)
- Provides access to Gemini Live API for audio streaming
- Handles authentication with GEMINI_API_KEY
- Manages bidirectional WebSocket communication
- **Essential for speech-to-speech call handling**

### `websockets` (>=11.0)
- WebSocket client library for Python
- Enables persistent bidirectional communication with Gemini API
- Handles real-time audio stream transmission
- Manages connection lifecycle and error recovery
- **Required for real-time audio streaming**

---

## Expected Log After Installation

Before (with error):
```
[ERROR] [Gemini Live] google-generativeai not installed
[ERROR] [Gemini Live] Install: pip install google-generativeai websockets
[ERROR] [Gemini Live] Client initialization failed
```

After (successful):
```
[Gemini Live] ✅ Client initialized successfully
[Gemini Live]    ├─ Model: gemini-2.5-flash-native-audio-preview-12-2025
[Gemini Live]    ├─ Voice: Aoede
[Gemini Live]    ├─ Audio Config: {'encoding': 'LINEAR16', 'sample_rate_hertz': 8000}
[Gemini Live]    ├─ Temperature: 0.3
[Gemini Live]    └─ Max Tokens: 500
```

---

## Troubleshooting

### If pip install fails

**Option 1: Use Python 3.12 specifically**
```bash
python3.12 -m pip install google-generativeai websockets
```

**Option 2: Check pip version**
```bash
pip --version
python -m pip install --upgrade pip
```

**Option 3: Check internet connectivity**
```bash
ping pypi.org
# If no response, check network firewall/proxy settings
```

### If import still fails

**Verify installation location:**
```bash
python -c "import google.generativeai as genai; print(genai.__file__)"
```

**List installed packages:**
```bash
pip list | grep -E "google|websockets"
```

Expected output:
```
google-generativeai  0.4.0
websockets           11.0
```

### If old version is installed

**Upgrade packages:**
```bash
pip install --upgrade google-generativeai websockets
```

---

## Full Production Deployment Checklist

- [ ] Activate virtual environment: `source venv/bin/activate`
- [ ] Install Gemini Live dependencies: `pip install -r requirements_gemini.txt`
- [ ] Verify installation: `python -c "import google.generativeai; print('✅')"` 
- [ ] Copy fixed files from local development
- [ ] Run import verification: `python verify_all_imports.py`
- [ ] Start application: `python main.py`
- [ ] Verify logs show: `[Gemini Live] ✅ Client initialized successfully`
- [ ] Test incoming call to verify Gemini audio streaming works
- [ ] Monitor logs for 5+ minutes to ensure stability

---

## Estimated Installation Time

- Package download: 2-5 minutes (depending on internet speed)
- Installation: 1-2 minutes
- **Total: 3-7 minutes**

---

## Status

After installation:
- ✅ google-generativeai available
- ✅ websockets available  
- ✅ Gemini Live can initialize client
- ✅ Audio streaming will work
- ✅ Greeting will play
- ✅ Full call flow operational

**Run this immediately on production server to get Gemini Live audio streaming working!** 🚀
