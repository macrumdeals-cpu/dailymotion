
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
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

# 1. التحقق من مفاتيح التشغيل
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

if not GEMINI_API_KEY or not PEXELS_API_KEY:
    raise ValueError("يرجى التأكد من ضبط GEMINI_API_KEY و PEXELS_API_KEY داخل GitHub Secrets!")

# 2. توليد السكريبت عبر Gemini
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

# 3. توليد التعليق الصوتي والترجمة الإنجليزية (Edge-TTS)
async def generate_audio_and_subtitles(text, audio_path="audio.mp3", srt_path="subtitles.srt"):
    voice = "en-US-ChristopherNeural"
    communicate = edge_tts.Communicate(text, voice)
    submaker = edge_tts.SubMaker()
    
    with open(audio_path, "wb") as file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)
                
    with open(srt_path, "w", encoding="utf-8") as file:
        file.write(submaker.get_srt())
    print("=== Audio & Subtitles Generated Successfully ===")

# 4. جلب فيديوهات الخلفية من Pexels
def fetch_pexels_videos(queries, target_count=6):
    headers = {"Authorization": PEXELS_API_KEY}
    downloaded_files = []
    
    for query in queries:
        url = f"https://api.pexels.com/videos/search?query={query}&per_page=4&orientation=portrait"
        res = requests.get(url, headers=headers).json()
        videos = res.get("videos", [])
        
        for vid in videos:
            video_files = vid.get("video_files", [])
            best_file = None
            for vf in video_files:
                if vf.get("height", 0) >= 1280 and vf.get("width", 0) <= vf.get("height", 0):
                    best_file = vf["link"]
                    break
            if not best_file and video_files:
                best_file = video_files[0]["link"]
                
            if best_file:
                file_path = f"bg_{len(downloaded_files)}.mp4"
                v_data = requests.get(best_file).content
                with open(file_path, "wb") as f:
                    f.write(v_data)
                downloaded_files.append(file_path)
                if len(downloaded_files) >= target_count:
                    break
        if len(downloaded_files) >= target_count:
            break
            
    return downloaded_files

# 5. المونتاج الحركي المكتمل عبر MoviePy و FFmpeg
def build_final_video(video_files, audio_path, output_path="final_video.mp4"):
    audio = AudioFileClip(audio_path)
    audio_duration = audio.duration
    
    clips = []
    clip_duration = 2.5
    current_time = 0
    file_idx = 0
    
    while current_time < audio_duration:
        v_file = video_files[file_idx % len(video_files)]
        clip = VideoFileClip(v_file)
        
        clip = clip.resize(height=1920)
        if clip.width < 1080:
            clip = clip.resize(width=1080)
        clip = clip.crop(x_center=clip.width/2, y_center=clip.height/2, width=1080, height=1920)
        
        dur = min(clip_duration, audio_duration - current_time)
        max_start = max(0, clip.duration - dur)
        start_p = random.uniform(0, max_start) if max_start > 0 else 0
        
        sub_clip = clip.subclip(start_p, start_p + dur)
        clips.append(sub_clip)
        current_time += dur
        file_idx += 1
        
    final_clip = concatenate_videoclips(clips, method="compose")
    final_clip = final_clip.set_audio(audio)
    
    temp_output = "temp_video.mp4"
    final_clip.write_videofile(temp_output, fps=30, codec="libx264", audio_codec="aac")
    
    cmd = (
        f'ffmpeg -y -i {temp_output} -vf '
        f'"subtitles=subtitles.srt:force_style=\'FontSize=20,FontName=Arial,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=2,MarginV=140\''
        f' -c:a copy {output_path}'
    )
    subprocess.run(cmd, shell=True)
    print(f"=== Process Complete: {output_path} Created ===")

# 6. نقطة التشغيل الرئيسية
if __name__ == "__main__":
    print("=== Starting Video Generation Pipeline ===")
    script_data = generate_script()
    asyncio.run(generate_audio_and_subtitles(script_data["script"]))
    bg_files = fetch_pexels_videos(script_data["search_queries"])
    build_final_video(bg_files, "audio.mp3", "final_video.mp4")
