import os
from pathlib import Path
from dotenv import load_dotenv
from groq import Groq

load_dotenv(Path(r"C:\Users\arikathotahruday\Downloads\Del_gov_delta-main\backend\.env"))
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
print("AVAILABLE_MODELS")
for item in client.models.list().data[:20]:
    print(item.id)
for model in ["qwen/qwen3.6-27b","qwen/qwen3.8-27b","openai/gpt-oss-20b","openai/gpt-oss-120b"]:
    try:
        r = client.chat.completions.create(model=model, messages=[{"role":"user","content":"hi"}], max_tokens=5)
        print("OK", model, ":", r.choices[0].message.content[:80])
    except Exception as e:
        print("FAIL", model, type(e).__name__, str(e)[:200])
