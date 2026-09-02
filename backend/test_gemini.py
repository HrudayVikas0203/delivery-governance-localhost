from app.core.config import get_settings
from google import genai

settings = get_settings()
print(f"Key exists: {bool(settings.gemini_api_key)}")
print(f"Model: {settings.gemini_default_model}")

client = genai.Client(api_key=settings.gemini_api_key)
print("Client initialized")
