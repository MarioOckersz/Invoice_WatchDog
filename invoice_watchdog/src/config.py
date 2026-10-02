import os
from dotenv import load_dotenv

# search mechanism to find .env file and load 
load_dotenv()

# loads th api key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Guard clause: Fail fast if the user hasn't configured their API key
if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
    raise ValueError(
        "❌ Missing GEMINI_API_KEY. Please create a .env file and set your API key from Google AI Studio."
    )