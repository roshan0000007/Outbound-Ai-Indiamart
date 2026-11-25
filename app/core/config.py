"""
Core Configuration Module
Loads environment variables and provides application settings
Minimal configuration for clean calling flow only
"""
import os
import logging
import struct
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ai_agent")

# ═══════════════════════════════════════════════════════════
# APPLICATION SETTINGS
# ═══════════════════════════════════════════════════════════
APP_NAME = os.getenv("APP_NAME", "AI Agent")
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8111"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ═══════════════════════════════════════════════════════════
# ASTERISK ARI CONFIGURATION
# ═══════════════════════════════════════════════════════════
ASTERISK_IP = os.getenv("ASTERISK_IP", "163.223.186.31")
MY_PC_IP = os.getenv("MY_PC_IP", "163.223.186.31")
ARI_USER = os.getenv("ARI_USER", "ai-agent-user")
ARI_PASS = os.getenv("ARI_PASS", "ai_secure_password")
ARI_URL = f"http://{ASTERISK_IP}:8088"
STASIS_APP = os.getenv("STASIS_APP", "aiagent")
AGENT_CONTEXT = os.getenv("AGENT_CONTEXT", "agent_context")
AGENT_EXT = os.getenv("AGENT_EXT", "agent")
AGENT_PRIORITY = int(os.getenv("AGENT_PRIORITY", "1"))

# RTP Configuration
PUBLIC_RTP_IP = os.getenv("PUBLIC_RTP_IP", "163.223.186.31").strip() or None
RTP_IP = os.getenv("RTP_IP", "0.0.0.0")
RTP_START_PORT = int(os.getenv("RTP_START_PORT", os.getenv("START_PORT", "10000")))
RTP_END_PORT = int(os.getenv("RTP_END_PORT", os.getenv("END_PORT", "20000")))
START_PORT = RTP_START_PORT
END_PORT = RTP_END_PORT

log.info(f"[CONFIG] RTP port range: {RTP_START_PORT}-{RTP_END_PORT}")

# RTP Audio Parameters
RTP_SAMPLE_RATE = 8000
RTP_PACKET_MS = 20
RTP_FRAME_SIZE = 160
RTP_HDR_FMT = struct.Struct("!BBHII")
RTP_PORT_QUARANTINE_DURATION_S = float(os.getenv("RTP_PORT_QUARANTINE_DURATION_S", "2.0"))
RTP_QUEUE_SIZE = int(os.getenv("RTP_QUEUE_SIZE", "2000"))

SUPPORTED_CODECS = {
    8: ("PCMA", 8000, 1),
    0: ("PCMU", 8000, 1),
}

# ═══════════════════════════════════════════════════════════
# RTP IP CONFIGURATION
# ═══════════════════════════════════════════════════════════
LOCAL_RTP_IP = os.getenv("LOCAL_RTP_IP", "0.0.0.0")
GREETING_RTP_WAIT_S = float(os.getenv("GREETING_RTP_WAIT_S", "2.0"))

# ═══════════════════════════════════════════════════════════
# AUDIO CODEC COMFORT NOISE
# ═══════════════════════════════════════════════════════════
RTP_COMFORT_NOISE_ULAW = b'\xff' * 160  # Silence frame in µLaw format

# ═══════════════════════════════════════════════════════════
# AUDIO MUTING CONFIGURATION (During AI Speaking)
# ═══════════════════════════════════════════════════════════
AUDIO_MUTING_ENABLED = os.getenv("AUDIO_MUTING_ENABLED", "true").lower() == "true"
AUDIO_MUTING_POST_TTS_CLEAR_DELAY_MS = int(os.getenv("AUDIO_MUTING_POST_TTS_CLEAR_DELAY_MS", "200"))
PREFLUSH_RX_BUFFER_STALE_FRAMES = int(os.getenv("PREFLUSH_RX_BUFFER_STALE_FRAMES", "20"))

# ═══════════════════════════════════════════════════════════
# DATABASE CONFIGURATION
# ═══════════════════════════════════════════════════════════
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", "password"))
DB_NAME = os.getenv("DB_NAME", "aiagent_db")
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "10"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "150"))

DATABASE_URL = f"mysql+aiomysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"

# ═══════════════════════════════════════════════════════════
# REDIS CONFIGURATION
# ═══════════════════════════════════════════════════════════
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "2000"))
REDIS_SOCKET_TIMEOUT = int(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))

REDIS_URL = (
    f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
    if REDIS_PASSWORD
    else f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
)

# ═══════════════════════════════════════════════════════════
# GEMINI LIVE API CONFIGURATION
# ═══════════════════════════════════════════════════════════
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")
GEMINI_VOICE = os.getenv("GEMINI_VOICE", "Aoede")

# Gemini Live Audio Streaming Configuration
GEMINI_AUDIO_STREAMING_ENABLED = os.getenv("GEMINI_AUDIO_STREAMING_ENABLED", "true").lower() == "true"
GEMINI_AUDIO_BUFFER_SIZE = int(os.getenv("GEMINI_AUDIO_BUFFER_SIZE", "1000"))
GEMINI_AUDIO_TIMEOUT_SEC = int(os.getenv("GEMINI_AUDIO_TIMEOUT_SEC", "300"))
GEMINI_AUDIO_BATCH_SIZE = int(os.getenv("GEMINI_AUDIO_BATCH_SIZE", "10"))

# ═══════════════════════════════════════════════════════════
# GROQ LLM CONFIGURATION (Fallback)
# ═══════════════════════════════════════════════════════════
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "mixtral-8x7b-32768")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "500"))

# ═══════════════════════════════════════════════════════════
# AUDIO PARAMETERS
# ═══════════════════════════════════════════════════════════
# 8kHz PCM - Standard for Asterisk and Gemini Live
AUDIO_SAMPLE_RATE = 8000
AUDIO_FRAME_SIZE = 160  # 20ms frame at 8kHz

# ═══════════════════════════════════════════════════════════
# LANGUAGE CONFIGURATION
# ═══════════════════════════════════════════════════════════
SUPPORTED_LANGUAGES = {
    "hi": "hi-IN",
    "en": "en-IN",
}
DEFAULT_LANGUAGE = "en"

# ═══════════════════════════════════════════════════════════
# CONVERSATION CONFIGURATION
# ═══════════════════════════════════════════════════════════
MAX_CONVERSATION_HISTORY = int(os.getenv("MAX_CONVERSATION_HISTORY", "16"))
MAX_ACTIVE_CALLS = int(os.getenv("MAX_ACTIVE_CALLS", "200"))

# ═══════════════════════════════════════════════════════════
# AUDIO FILTERING CONFIGURATION (Optional - Disabled by default)
# NOTE: DeepFilterNet and WebRTC VAD are legacy and not recommended
# Gemini Live handles all audio processing natively
# ═══════════════════════════════════════════════════════════
DEEPFILTERNET_ENABLED = os.getenv("DEEPFILTERNET_ENABLED", "false").lower() == "true"
DEEPFILTERNET_FRAME_LATENCY_MS = int(os.getenv("DEEPFILTERNET_FRAME_LATENCY_MS", "20"))
DEEPFILTERNET_FALLBACK_THRESHOLD_MS = int(os.getenv("DEEPFILTERNET_FALLBACK_THRESHOLD_MS", "50"))
DEEPFILTERNET_POST_FILTER_ENABLED = os.getenv("DEEPFILTERNET_POST_FILTER_ENABLED", "true").lower() == "true"

# ═══════════════════════════════════════════════════════════
# BARGE-IN GATING CONFIGURATION (Optional)
# ═══════════════════════════════════════════════════════════
NOISE_FLOOR_RMS = int(os.getenv("NOISE_FLOOR_RMS", "800"))
SPEECH_RMS_FLOOR = int(os.getenv("SPEECH_RMS_FLOOR", "2000"))

# ═══════════════════════════════════════════════════════════
# WEBRTC VOICE ACTIVITY DETECTION (Optional - Not Recommended)
# ═══════════════════════════════════════════════════════════
WEBRTC_NS_LEVEL = int(os.getenv("WEBRTC_NS_LEVEL", "2"))

# ═══════════════════════════════════════════════════════════
# WORKER THREADS
# ═══════════════════════════════════════════════════════════
THREAD_POOL_SIZE = int(os.getenv("THREAD_POOL_SIZE", "250"))
DB_WORKERS = int(os.getenv("DB_WORKERS", "70"))
