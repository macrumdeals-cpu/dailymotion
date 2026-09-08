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
        model='gemini-3.5-flash-lite',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    
    data = json.loads(response.text)
    print("=== English Script Generated Successfully ===")
    print("Title:", data.get("title"))
    return data
# -------------------------------------------------------------
# نقطة التشغيل الرئيسية (مهمة جداً لبدء التنفيذ)
# -------------------------------------------------------------
if __name__ == "__main__":
    print("=== Starting Video Generation Pipeline ===")
    script_data = generate_script()
    asyncio.run(generate_audio_and_subtitles(script_data["script"]))
    bg_files = fetch_pexels_videos(script_data["search_queries"])
    build_final_video(bg_files, "audio.mp3", "final_video.mp4")
