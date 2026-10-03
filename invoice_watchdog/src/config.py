import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Default to gemini-2.5-flash if not explicitly set
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
    raise ValueError(
        "❌ Missing GEMINI_API_KEY. Please create a .env file and set your API key from Google AI Studio."
    )