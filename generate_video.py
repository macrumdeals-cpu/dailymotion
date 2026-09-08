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

# 1. جلب المفاتيح من Secrets
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

DAILYMOTION_CLIENT_ID = os.environ.get("DAILYMOTION_CLIENT_ID")
DAILYMOTION_CLIENT_SECRET = os.environ.get("DAILYMOTION_CLIENT_SECRET")
DAILYMOTION_USERNAME = os.environ.get("DAILYMOTION_USERNAME")
DAILYMOTION_PASSWORD = os.environ.get("DAILYMOTION_PASSWORD")

# 2. إدارة ملف السجل لمنع التكرار
HISTORY_FILE = "history.json"

def get_used_topics():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_topic_to_history(title):
    history = get_used_topics()
    history.append(title)
    # الاحتفاظ بآخر 100 موضوع لمنع التضخم
    history = history[-100:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

# 3. توليد السكريبت غير المكرر عبر Gemini
def generate_script():
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    used_topics = get_used_topics()
    
    categories = [
        "Mind-blowing Science & Brain Facts",
        "Psychology & Human Behavior Tricks",
        "Personal Finance & Money Secrets",
        "Future Tech & AI Innovations",
        "Life-changing Productivity Hacks",
        "Mysterious Unsolved Facts"
    ]
    selected_category = random.choice(categories)
    
    prompt = f"""
    You are an expert viral YouTube Shorts & TikTok content creator.
    Category for this video: {selected_category}.
    
    STRICT RULES TO PREVENT DUPLICATION:
    - DO NOT use or repeat any of these previously used titles/topics: {json.dumps(used_topics)}
    - Pick a UNIQUE, fresh, and captivating angle.
    - Video script length: 45 to 50 seconds (around 120-135 words).
    - First 3 seconds MUST start with a powerful hook question or mind-blowing statement to stop scrolling.
    - Output JSON ONLY with these exact keys:
       - "title": Video Title
       - "script": Full voiceover text
       - "search_queries": Array of 3 specific English keywords to fetch stock background videos (e.g., ["glowing brain network", "cyberpunk city", "luxurious gold aesthetic"])
    """
    
    response = client.models.generate_content(
        model='gemini-3.5-flash-lite',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=1.0,
        ),
    )
    
    data = json.loads(response.text)
    print("=== English Script Generated Successfully ===")
    print("Category:", selected_category)
    print("Title:", data.get("title"))
    
    save_topic_to_history(data.get("title"))
    return data

# 4. توليد التعليق الصوتي والترجمة الإنجليزية (Edge-TTS)
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

# 5. جلب فيديوهات الخلفية من Pexels
def fetch_pexels_videos(queries, target_count=6):
    headers = {"Authorization": PEXELS_API_KEY}
    downloaded_files = []
    
    for query in queries:
        url = f"https://api.pexels.com/videos/search?query={query}&per_page=5&orientation=portrait"
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

# 6. المونتاج الحركي
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
        if clip.w < 1080:
            clip = clip.resize(width=1080)
        clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=1080, height=1920)
        
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
    print(f"=== Video Creation Complete: {output_path} ===")

# 7. الرفع الأوتوماتيكي على Dailymotion
def upload_to_dailymotion(video_path, title):
    if not all([DAILYMOTION_CLIENT_ID, DAILYMOTION_CLIENT_SECRET, DAILYMOTION_USERNAME, DAILYMOTION_PASSWORD]):
        print("تنبيه: لم يتم ضبط جميع مفاتيح Dailymotion في Secrets، سيتم تجاوز الرفع.")
        return

    print("=== بدء عملية الرفع على Dailymotion ===")

    # الحصول على Access Token
    auth_url = "https://api.dailymotion.com/oauth/token"
    auth_data = {
        "grant_type": "password",
        "client_id": DAILYMOTION_CLIENT_ID,
        "client_secret": DAILYMOTION_CLIENT_SECRET,
        "username": DAILYMOTION_USERNAME,
        "password": DAILYMOTION_PASSWORD,
        "scope": "manage_videos"
    }
    auth_res = requests.post(auth_url, data=auth_data).json()
    access_token = auth_res.get("access_token")

    if not access_token:
        print("خطأ في الاتصال بـ Dailymotion:", auth_res)
        return

    headers = {"Authorization": f"Bearer {access_token}"}

    # الحصول على رابط الرفع
    url_res = requests.get("https://api.dailymotion.com/file/upload", headers=headers).json()
    upload_url = url_res.get("upload_url")

    # رفع الفيديو
    with open(video_path, "rb") as f:
        file_res = requests.post(upload_url, files={"file": f}).json()
    file_url = file_res.get("url")

    # نشر الفيديو
    publish_data = {
        "url": file_url,
        "title": title[:100],
        "tags": "shorts,viral,facts,trending",
        "published": "true",
        "channel": "lifestyle",
        "is_created_for_kids": "false"
    }
    publish_res = requests.post("https://api.dailymotion.com/me/videos", headers=headers, data=publish_data).json()
    print("=== تم النشر بنجاح على Dailymotion! ===")
    print("Video ID:", publish_res.get("id"))

# 8. التشغيل
if __name__ == "__main__":
    print("=== Starting Video Generation Pipeline ===")
    script_data = generate_script()
    asyncio.run(generate_audio_and_subtitles(script_data["script"]))
    bg_files = fetch_pexels_videos(script_data["search_queries"])
    build_final_video(bg_files, "audio.mp3", "final_video.mp4")
    upload_to_dailymotion("final_video.mp4", script_data["title"])
