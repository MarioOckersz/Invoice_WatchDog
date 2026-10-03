import os
from dotenv import load_dotenv, find_dotenv

dotenv_path = find_dotenv(usecwd=True)
if dotenv_path:
    load_dotenv(dotenv_path)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Primary model, with stable fallbacks for high-load / 503 protection
# If gemini-3.8-flash is saturated, it immediately falls back to stable production endpoints
MODEL_CANDIDATES = [
    os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

if not GEMINI_API_KEY:
    raise ValueError("❌ Missing GEMINI_API_KEY. Please check your .env file.")