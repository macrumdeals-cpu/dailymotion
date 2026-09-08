import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

import os
import json
import random
import asyncio
import requests
import subprocess
from datetime import datetime
import edge_tts
from google import genai
from google.genai import types
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips

# 1. جلب البيئة والمفاتيح
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

DAILYMOTION_CLIENT_ID = os.environ.get("DAILYMOTION_CLIENT_ID")
DAILYMOTION_CLIENT_SECRET = os.environ.get("DAILYMOTION_CLIENT_SECRET")
DAILYMOTION_USERNAME = os.environ.get("DAILYMOTION_USERNAME")
DAILYMOTION_PASSWORD = os.environ.get("DAILYMOTION_PASSWORD")

BLUESKY_HANDLE = os.environ.get("BLUESKY_HANDLE")
BLUESKY_PASSWORD = os.environ.get("BLUESKY_PASSWORD")

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
    history = history[-100:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

# 2. توليد السكريبت مع تحديد النوع (Short / Long Video) والقائمة
def generate_script():
    client = genai.Client(api_key=GEMINI_API_KEY)
    used_topics = get_used_topics()
    
    # تحديد نوع الفيديو عشوائياً
    video_type = random.choice(["LONG_SHORT", "STANDARD_VIDEO"])
    
    playlists_map = {
        "Educational & Science": "Educational Science & Facts",
        "Tech & Future AI": "Tech & AI Masterclass",
        "Psychology & Human Mind": "Psychology Secrets",
        "Money & Wealth Hacks": "Finance & Success Guides"
    }
    
    selected_category = random.choice(list(playlists_map.keys()))
    playlist_name = playlists_map[selected_category]
    
    if video_type == "LONG_SHORT":
        duration_instruction = "Duration: 55 to 60 seconds (around 140-150 words). Format is vertical short."
        orientation = "portrait"
    else:
        duration_instruction = "Duration: 90 to 120 seconds (around 220-250 words). Format is standard horizontal educational video."
        orientation = "landscape"

    prompt = f"""
    You are an expert viral content creator and educator.
    Category: {selected_category}.
    Video Type: {video_type}.
    {duration_instruction}
    
    STRICT RULES:
    - DO NOT repeat any of these topics: {json.dumps(used_topics)}
    - High retention educational hook in the first 3 seconds.
    - Output JSON ONLY with these exact keys:
       - "title": Video Title (Catchy, SEO friendly)
       - "script": Full engaging voiceover script
       - "search_queries": Array of 4 English keywords for stock videos
       - "bluesky_post": Short viral post for Bluesky with hashtags
    """
    
    response = client.models.generate_content(
        model='gemini-3.5-flash-lite',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.9,
        ),
    )
    
    data = json.loads(response.text)
    data["video_type"] = video_type
    data["orientation"] = orientation
    data["playlist_name"] = playlist_name
    
    print(f"=== Script Generated | Type: {video_type} | Category: {selected_category} ===")
    save_topic_to_history(data.get("title"))
    return data

# 3. توليد الصوت والترجمة
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

# 4. جلب الخلفيات بناءً على الأبعاد (رأسي أم أفقي)
def fetch_pexels_videos(queries, orientation, target_count=8):
    headers = {"Authorization": PEXELS_API_KEY}
    downloaded_files = []
    
    for query in queries:
        url = f"https://api.pexels.com/videos/search?query={query}&per_page=4&orientation={orientation}"
        res = requests.get(url, headers=headers).json()
        videos = res.get("videos", [])
        
        for vid in videos:
            video_files = vid.get("video_files", [])
            best_file = video_files[0]["link"] if video_files else None
            
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

# 5. المونتاج وتكييف الأبعاد
def build_final_video(video_files, audio_path, orientation, output_path="final_video.mp4"):
    audio = AudioFileClip(audio_path)
    audio_duration = audio.duration
    
    target_w, target_h = (1080, 1920) if orientation == "portrait" else (1920, 1080)
    
    clips = []
    clip_duration = 3.0
    current_time = 0
    file_idx = 0
    
    while current_time < audio_duration:
        v_file = video_files[file_idx % len(video_files)]
        clip = VideoFileClip(v_file)
        
        clip = clip.resize(height=target_h)
        if clip.w < target_w:
            clip = clip.resize(width=target_w)
        clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=target_w, height=target_h)
        
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
    
    margin_v = 140 if orientation == "portrait" else 60
    font_size = 20 if orientation == "portrait" else 16
    
    cmd = (
        f'ffmpeg -y -i {temp_output} -vf '
        f'"subtitles=subtitles.srt:force_style=\'FontSize={font_size},FontName=Arial,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,MarginV={margin_v}\''
        f' -c:a copy {output_path}'
    )
    subprocess.run(cmd, shell=True)

# 6. الرفع على Dailymotion وإدارته داخل البلاي ليست
def upload_to_dailymotion(video_path, title, playlist_name):
    if not all([DAILYMOTION_CLIENT_ID, DAILYMOTION_CLIENT_SECRET, DAILYMOTION_USERNAME, DAILYMOTION_PASSWORD]):
        print("تنبيه: مفاتيح Dailymotion غير مكتملة.")
        return None

    # Token Authentication
    auth_url = "https://api.dailymotion.com/oauth/token"
    auth_data = {
        "grant_type": "password",
        "client_id": DAILYMOTION_CLIENT_ID,
        "client_secret": DAILYMOTION_CLIENT_SECRET,
        "username": DAILYMOTION_USERNAME,
        "password": DAILYMOTION_PASSWORD,
        "scope": "manage_videos manage_playlists"
    }
    auth_res = requests.post(auth_url, data=auth_data).json()
    access_token = auth_res.get("access_token")
    headers = {"Authorization": f"Bearer {access_token}"}

    # Upload File
    url_res = requests.get("https://api.dailymotion.com/file/upload", headers=headers).json()
    upload_url = url_res.get("upload_url")

    with open(video_path, "rb") as f:
        file_res = requests.post(upload_url, files={"file": f}).json()
    file_url = file_res.get("url")

    # Publish Video
    publish_data = {
        "url": file_url,
        "title": title[:100],
        "tags": "education,facts,shorts,learning,viral",
        "published": "true",
        "channel": "tech",
        "is_created_for_kids": "false"
    }
    publish_res = requests.post("https://api.dailymotion.com/me/videos", headers=headers, data=publish_data).json()
    video_id = publish_res.get("id")
    video_link = f"https://www.dailymotion.com/video/{video_id}"
    print("=== Published to Dailymotion:", video_link)

    # Manage Playlists
    try:
        user_playlists = requests.get("https://api.dailymotion.com/me/playlists", headers=headers).json().get("list", [])
        playlist_id = None
        for pl in user_playlists:
            if pl.get("name") == playlist_name:
                playlist_id = pl.get("id")
                break
                
        if not playlist_id:
            new_pl = requests.post("https://api.dailymotion.com/me/playlists", headers=headers, data={"name": playlist_name}).json()
            playlist_id = new_pl.get("id")

        if playlist_id:
            requests.post(f"https://api.dailymotion.com/playlist/{playlist_id}/videos", headers=headers, data={"videoid": video_id})
            print(f"=== Added Video to Playlist: {playlist_name} ===")
    except Exception as e:
        print("Playlist Error:", e)

    return video_link

# 7. المشاركة التلقائية على Bluesky
def post_to_bluesky(text_content, video_url):
    if not BLUESKY_HANDLE or not BLUESKY_PASSWORD or not video_url:
        return
        
    try:
        # Auth Session
        session_res = requests.post(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            json={"identifier": BLUESKY_HANDLE, "password": BLUESKY_PASSWORD}
        ).json()
        
        token = session_res.get("accessJwt")
        did = session_res.get("did")
        
        post_text = f"{text_content}\n\nWatch full video here: {video_url}"
        
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "repo": did,
            "collection": "app.bsky.feed.post",
            "record": {
                "$type": "app.bsky.feed.post",
                "text": post_text,
                "createdAt": datetime.utcnow().isoformat() + "Z"
            }
        }
        
        res = requests.post("https://api.dailymotion.com/xrpc/com.atproto.repo.createRecord", headers=headers, json=payload)
        print("=== Shared Successfully to Bluesky! ===")
    except Exception as e:
        print("Bluesky Post Error:", e)

# 8. التشغيل
if __name__ == "__main__":
    script_data = generate_script()
    asyncio.run(generate_audio_and_subtitles(script_data["script"]))
    bg_files = fetch_pexels_videos(script_data["search_queries"], script_data["orientation"])
    build_final_video(bg_files, "audio.mp3", script_data["orientation"], "final_video.mp4")
    
    video_url = upload_to_dailymotion("final_video.mp4", script_data["title"], script_data["playlist_name"])
    if video_url:
        post_to_bluesky(script_data["bluesky_post"], video_url)
