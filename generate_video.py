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

# 2. توليد السكريبت
def generate_script():
    client = genai.Client(api_key=GEMINI_API_KEY)
    used_topics = get_used_topics()
    
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
        model='gemini-3-flash-preview',
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

# 3. جلب فيديوهات الخلفية من Pexels
def fetch_pexels_videos(queries, orientation="portrait", count_per_query=2):
    if not PEXELS_API_KEY:
        raise ValueError("PEXELS_API_KEY is missing!")

    headers = {"Authorization": PEXELS_API_KEY}
    downloaded_files = []

    for query in queries:
        url = f"https://api.pexels.com/videos/search?query={query}&orientation={orientation}&per_page={count_per_query}"
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            videos = data.get("videos", [])
            for vid in videos:
                video_files = vid.get("video_files", [])
                video_files.sort(key=lambda x: x.get("width", 0), reverse=True)
                if video_files:
                    video_url = video_files[0].get("link")
                    file_name = f"bg_video_{len(downloaded_files)}.mp4"
                    
                    res = requests.get(video_url, stream=True)
                    with open(file_name, "wb") as f:
                        for chunk in res.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    
                    downloaded_files.append(file_name)
        else:
            print(f"Pexels API Error for '{query}': Status {response.status_code}")

    if not downloaded_files:
        raise Exception("Failed to download videos from Pexels!")

    print(f"=== Downloaded {len(downloaded_files)} videos from Pexels ===")
    return downloaded_files

# 4. توليد التعليق الصوتي والترجمة
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
                
    srt_content = submaker.get_srt()
    
    if not srt_content or not srt_content.strip():
        srt_content = f"1\n00:00:00,000 --> 00:01:00,000\n{text}\n"
        
    with open(srt_path, "w", encoding="utf-8") as file:
        file.write(srt_content)
        file.flush()
        os.fsync(file.fileno())
        
    print("=== Audio & Subtitles Generated Successfully ===")

# 5. المونتاج وتطبيق الترجمة
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
    
    srt_file = "subtitles.srt"
    has_valid_subtitles = os.path.exists(srt_file) and os.path.getsize(srt_file) > 0
    
    if has_valid_subtitles:
        subtitle_filter = f"subtitles={srt_file}:force_style='FontSize={font_size},FontName=Arial,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,MarginV={margin_v}'"
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_output,
            "-vf", subtitle_filter,
            "-c:a", "copy",
            output_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_output,
            "-c:v", "copy",
            "-c:a", "copy",
            output_path
        ]
        
    subprocess.run(cmd, check=True)
    print("=== Final Video Built Successfully! ===")

# 6. الرفع على Dailymotion
def upload_to_dailymotion(video_path, title, playlist_name):
    if not all([DAILYMOTION_CLIENT_ID, DAILYMOTION_CLIENT_SECRET, DAILYMOTION_USERNAME, DAILYMOTION_PASSWORD]):
        print("تنبيه: مفاتيح Dailymotion غير مكتملة.")
        return None

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

    url_res = requests.get("https://api.dailymotion.com/file/upload", headers=headers).json()
    upload_url = url_res.get("upload_url")

    with open(video_path, "rb") as f:
        file_res = requests.post(upload_url, files={"file": f}).json()
    file_url = file_res.get("url")

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
        
        # تصحيح رابط الطلب إلى Bluesky بدلاً من Dailymotion
        res = requests.post("https://bsky.social/xrpc/com.atproto.repo.createRecord", headers=headers, json=payload)
        print("=== Shared Successfully to Bluesky! ===")
    except Exception as e:
        print("Bluesky Post Error:", e)

# 8. التشغيل الرئيسي
if __name__ == "__main__":
    script_data = generate_script()
    asyncio.run(generate_audio_and_subtitles(script_data["script"]))
    bg_files = fetch_pexels_videos(script_data["search_queries"], script_data["orientation"])
    build_final_video(bg_files, "audio.mp3", script_data["orientation"], "final_video.mp4")
    
    video_url = upload_to_dailymotion("final_video.mp4", script_data["title"], script_data["playlist_name"])
    if video_url:
        post_to_bluesky(script_data["bluesky_post"], video_url)
