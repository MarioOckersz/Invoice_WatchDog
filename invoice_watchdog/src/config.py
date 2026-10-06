import os
from dotenv import load_dotenv, find_dotenv

dotenv_path = find_dotenv(usecwd=True)
if dotenv_path:
    load_dotenv(dotenv_path)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# High-reliability cascade based on your active available models:
# 1. gemini-flash-latest (Google routes to the most stable current endpoint)
# 2. gemini-3.7-flash (Recent stable release)
# 3. gemini-3.5-flash (Proven high-availability fallback)
# 4. gemini-3.8-flash (Latest, but falls back gracefully if 503 occurs)
MODEL_CANDIDATES = [
    os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
]

if not GEMINI_API_KEY:
    raise ValueError("❌ Missing GEMINI_API_KEY. Please check your .env file.")