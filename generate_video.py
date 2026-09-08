import os
import json
from google import genai
from google.genai import types

def generate_script():
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    
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
        model='gemini-1.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    
    data = json.loads(response.text)
    print("=== Gemini English Script Generated Successfully ===")
    print("Title:", data.get("title"))
    return data
