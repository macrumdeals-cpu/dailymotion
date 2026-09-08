import os
import json
import random
import asyncio
import requests
import subprocess
import edge_tts
from google import genai
from google.genai import types
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

if not GEMINI_API_KEY or not PEXELS_API_KEY:
    raise ValueError("يرجى ضبط GEMINI_API_KEY و PEXELS_API_KEY في إعدادات GitHub Secrets!")

def generate_script():
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = """
    You are an expert viral YouTube Shorts & TikTok content creator.
    Create an engaging English video script that lasts between 45 to 50 seconds (around 120-135 words).
    
    STRICT RULES:
    1. First 3 seconds MUST start with a powerful hook question or mind-blowing statement to stop scrolling.
    2. Use short, punchy sentences tailored for fast-paced video editing.
    3. Output JSON ONLY with these exact keys:
       - "title": Video Title
       - "script": Full voiceover text
       - "search_queries": Array of 3 specific English keywords to fetch stock background videos (e.g., ["cyberpunk city", "futuristic server", "glowing neon technology"])
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    
    data = json.loads(response.text)
    print("=== English Script Generated Successfully ===")
    print("Title:", data.get("title"))
    return data
