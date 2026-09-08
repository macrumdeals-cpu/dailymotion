import re
import time
import base64
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

import requests
from requests.auth import HTTPBasicAuth
import os
import json
import random
import asyncio
import subprocess
from datetime import datetime
import edge_tts
from google import genai
from google.genai import types
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips

# 1. جلب البيئة والمفاتيح
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

DAILYMOTION_USERNAME = os.environ.get("DAILYMOTION_USERNAME")
DAILYMOTION_PASSWORD = os.environ.get("DAILYMOTION_PASSWORD")

BLUESKY_HANDLE = os.environ.get("BLUESKY_HANDLE")
BLUESKY_PASSWORD = os.environ.get("BLUESKY_PASSWORD")

HISTORY_FILE = "history.json"

# فحص واعتماد الاتصال مع Dailymotion
def verify_dailymotion_auth():
    cid = os.environ.get("DAILYMOTION_CLIENT_ID")
    sec = os.environ.get("DAILYMOTION_CLIENT_SECRET")
    username = os.environ.get("DAILYMOTION_USERNAME")
    password = os.environ.get("DAILYMOTION_PASSWORD")

    if not all([cid, sec, username, password]):
        print("❌ مفاتيح Dailymotion ناقصة في الـ Secrets")
        return None

    auth_url = "https://api.dailymotion.com/oauth/token"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        res = requests.post(
            auth_url,
            data={
                "grant_type": "password",
                "client_id": cid,
                "client_secret": sec,
                "username": username,
                "password": password,
                "scope": "manage_videos manage_playlists manage_subscriptions userinfo"
            },
            headers=headers,
            timeout=15
        ).json()

        token = res.get("access_token")
        if token:
            print("✅ تم الاتصال بنجاح بحسابك على Dailymotion!")
            return token

        print("❌ استجابة Dailymotion:", res)
        return None

    except Exception as e:
        print("❌ خطأ في الاتصال:", e)
        return None

# جلب أفضل الفيديوهات أداءً على القناة لربط السكريبت بها
def fetch_top_performing_videos(access_token):
    if not access_token:
        return []
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        url = "https://api.dailymotion.com/me/videos?fields=title,views&sort=visited&limit=5"
        res = requests.get(url, headers=headers, timeout=15).json()
        videos = res.get("list", [])
        performers = [f"'{v.get('title')}' ({v.get('views', 0)} views)" for v in videos if v.get("title")]
        print(f"📊 تم تحليل أداء القناة: العثور على {len(performers)} فيديو عالي المشاهدة.")
        return performers
    except Exception as e:
        print("⚠️ تعذر جلب تحليلات القناة:", e)
        return []

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

# ==========================================
# 2. محرك جلب التريندات العالمية الحيّة
# ==========================================
def fetch_rss_titles(feed_url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        res = requests.get(feed_url, headers=headers, timeout=7)
        titles = re.findall(r'<title>(.*?)</title>', res.text)
        cleaned = [re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', t).strip() for t in titles]
        return [t for t in cleaned if len(t) > 10 and "RSS" not in t and "Feed" not in t]
    except Exception:
        return []

def fetch_from_reddit():
    url = "https://www.reddit.com/r/todayilearned/hot.json?limit=30"
    headers = {'User-Agent': 'python:trending.shorts.bot:v2.0'}
    try:
        res = requests.get(url, headers=headers, timeout=7)
        if res.status_code == 200:
            posts = res.json().get('data', {}).get('children', [])
            return [p['data']['title'].replace("TIL ", "").replace("TIL that ", "") for p in posts if 'title' in p['data']]
    except Exception:
        pass
    return []

def fetch_from_wikipedia():
    url = "https://en.wikipedia.org/api/rest_v1/feed/featured/today"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=7).json()
        most_read = res.get('mostread', {}).get('articles', [])
        return [article['title'].replace("_", " ") for article in most_read if 'title' in article]
    except Exception:
        return []

def get_strictly_new_trending_topic():
    used_topics = get_used_topics()
    used_topics_lower = set(t.lower().strip() for t in used_topics)
    
    sources = [
        ("Google Trends RSS", lambda: fetch_rss_titles("https://trends.google.com/trends/trendingsearches/daily/rss?geo=US")),
        ("BBC World News RSS", lambda: fetch_rss_titles("http://feeds.bbci.co.uk/news/world/rss.xml")),
        ("TechCrunch RSS", lambda: fetch_rss_titles("https://techcrunch.com/feed/")),
        ("Reddit TIL", fetch_from_reddit),
        ("Wikipedia Featured", fetch_from_wikipedia)
    ]
    random.shuffle(sources)

    for source_name, source_func in sources:
        try:
            print(f"🔍 Searching trends from: {source_name}...")
            topics = source_func()
            fresh_topics = [
                t for t in topics 
                if t.lower().strip() not in used_topics_lower 
                and len(t.strip()) > 12
                and not t.strip().isdigit()
            ]
            
            if fresh_topics:
                selected = random.choice(fresh_topics)
                print(f"🔥 Found NEW Trending Topic from {source_name}: '{selected}'")
                return selected
        except Exception as e:
            print(f"⚠️ Failed fetching from {source_name}: {e}")

    print("⚠️ Fallback to default trending topic...")
    return "Latest Breakthroughs in Global Technology and Science"

# ==========================================
# 3. توليد السكريبت والوصف بناءً على التريند
# ==========================================
def generate_script(top_performers=[]):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # جلب موضوع تريند حقيقي من المصادر العالمية
    trending_topic = get_strictly_new_trending_topic()
    
    video_type = "LONG_SHORT"
    playlist_name = "Trending World News & Facts"
    
    duration_instruction = "Duration: 40 to 50 seconds (around 100-120 words). Vertical short format."
    orientation = "portrait"

    analytics_context = ""
    if top_performers:
        analytics_context = f"Top Performing Videos on Channel: {', '.join(top_performers)}. Create content matching this engagement style."

    prompt = f"""
    You are an expert viral content creator & SEO specialist skilled in YouTube Shorts, Dailymotion, and social media growth.
    Main Trending News/Topic: '{trending_topic}'.
    Video Type: {video_type}.
    {duration_instruction}
    {analytics_context}
    
    STRICT VIRAL FORMATTING RULES:
    - "title": MUST be a catchy hook with an emoji about the topic, and MUST END STRICTLY with "#shorts #viral" (Example: "Mind-Blowing Discovery! 📱 #shorts #viral").
    - "description": MUST start with an intriguing hook sentence, followed by a brief 2-sentence summary of '{trending_topic}', and end with "👇 SUBSCRIBE for more mind-blowing content!".
    - "bluesky_post": A short viral post (under 200 characters) starting with an exciting hook emoji, brief teaser line, and ending with hashtags "#shorts #viral #trending".
    - "tags": Array of 8 to 12 relevant SEO tags matching this topic.
    - "script": Full engaging voiceover script (100-120 words max).
    - "search_queries": Array of 4 simple English keywords matching this topic for Pexels stock videos (e.g., nature, space, technology, city).

    Output JSON ONLY with these exact keys:
    "title", "description", "tags", "script", "search_queries", "bluesky_post"
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
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
    
    print(f"=== Script Generated for Trend: {trending_topic} ===")
    save_topic_to_history(trending_topic)
    save_topic_to_history(data.get("title"))
    return data

# 4. جلب فيديوهات الخلفية من Pexels
def fetch_pexels_videos(queries, orientation="portrait", count_per_query=2):
    if not PEXELS_API_KEY:
        raise ValueError("PEXELS_API_KEY is missing!")

    headers = {"Authorization": PEXELS_API_KEY}
    downloaded_files = []

    for query in queries:
        url = f"https://api.pexels.com/videos/search?query={query}&orientation={orientation}&per_page={count_per_query}"
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            videos = data.get("videos", [])
            for vid in videos:
                video_files = vid.get("video_files", [])
                video_files.sort(key=lambda x: x.get("width", 0), reverse=True)
                if video_files:
                    video_url = video_files[0].get("link")
                    file_name = f"bg_video_{len(downloaded_files)}.mp4"
                    
                    res = requests.get(video_url, stream=True, timeout=15)
                    with open(file_name, "wb") as f:
                        for chunk in res.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    
                    downloaded_files.append(file_name)
        else:
            print(f"Pexels API Error for '{query}': Status {response.status_code}")

    if not downloaded_files:
        raise Exception("Failed to download videos from Pexels!")

    print(f"=== Downloaded {len(downloaded_files)} background clips ===")
    return downloaded_files

# 5. توليد التعليق الصوتي والترجمة
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
        
    print("=== Audio & Subtitles Generated ===")

# 6. المونتاج المحسن
def build_final_video(video_files, audio_path, orientation, output_path="final_video.mp4"):
    audio = AudioFileClip(audio_path)
    audio_duration = audio.duration
    
    target_w, target_h = (1080, 1920)
    
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
    
    print("=== Processing Video Render (Please wait)... ===")
    final_clip.write_videofile(
        temp_output,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        threads=1,
        preset="ultrafast",
        verbose=False,
        logger=None
    )
    
    margin_v = 180
    font_size = 22
    srt_file = "subtitles.srt"
    has_valid_subtitles = os.path.exists(srt_file) and os.path.getsize(srt_file) > 0
    
    if has_valid_subtitles:
        subtitle_filter = f"subtitles={srt_file}:force_style='FontSize={font_size},FontName=Arial,Bold=1,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,MarginV={margin_v},Alignment=2'"
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

# 7. الرفع المباشر لـ Dailymotion
def upload_to_dailymotion(access_token, video_path, title, description, tags, playlist_name):
    if not access_token:
        return None

    headers = {"Authorization": f"Bearer {access_token}"}

    # 1. طلب رابط الرفع
    url_res = requests.get("https://api.dailymotion.com/file/upload", headers=headers).json()
    upload_url = url_res.get("upload_url")

    if not upload_url:
        print("=== فشل الحصول على رابط الرفع ===")
        return None

    # 2. رفع ملف الفيديو
    with open(video_path, "rb") as f:
        file_res = requests.post(upload_url, files={"file": f}).json()
    file_url = file_res.get("url")

    if not file_url:
        print("=== فشل رفع الملف ===")
        return None

    tags_string = ",".join(tags) if isinstance(tags, list) else str(tags)

    publish_data = {
        "url": file_url,
        "title": title[:100],
        "description": description,
        "tags": tags_string,
        "published": "true",
        "channel": "news",
        "language": "en",
        "is_created_for_kids": "false"
    }
    
    # 3. نشر الفيديو والحصول على المعرف
    publish_res = requests.post("https://api.dailymotion.com/me/videos", headers=headers, data=publish_data).json()
    video_id = publish_res.get("id")
    
    if not video_id:
        print("=== فشل نشر الفيديو ===", publish_res)
        return None

    video_link = f"https://www.dailymotion.com/video/{video_id}"
    print("=== Published to Dailymotion with Full SEO Meta:", video_link)

    # 4. إضافة الفيديو إلى قائمة التشغيل بعد مهلة معالجة
    try:
        print("⏳ الانتظار 5 ثوانٍ لضمان تسجيل الفيديو في السيرفر...")
        time.sleep(5)

        user_playlists = requests.get("https://api.dailymotion.com/me/playlists?limit=100", headers=headers).json().get("list", [])
        playlist_id = None
        
        for pl in user_playlists:
            if pl.get("name") == playlist_name:
                playlist_id = pl.get("id")
                break
                
        if not playlist_id:
            new_pl = requests.post("https://api.dailymotion.com/me/playlists", headers=headers, data={"name": playlist_name}).json()
            playlist_id = new_pl.get("id")

        if playlist_id:
            add_url = f"https://api.dailymotion.com/playlist/{playlist_id}/videos"
            pl_res = requests.post(add_url, headers=headers, data={"videoid": video_id})
            
            if pl_res.status_code in [200, 201]:
                print(f"=== Added Video ({video_id}) to Playlist: {playlist_name} Successfully! ===")
            else:
                print(f"❌ فشل إضافة الفيديو للقائمة: {pl_res.text}")

    except Exception as e:
        print("❌ Playlist Error:", e)

    return video_link

# استخراج الـ Facets لنشر روابط قابلة للنقر في Bluesky
def extract_bluesky_facets(text):
    facets = []
    url_regex = r'(https?://[^\s]+)'
    
    for match in re.finditer(url_regex, text):
        url = match.group(0)
        start_byte = len(text[:match.start()].encode('utf-8'))
        end_byte = len(text[:match.end()].encode('utf-8'))
        
        facets.append({
            "index": {
                "byteStart": start_byte,
                "byteEnd": end_byte
            },
            "features": [{
                "$type": "app.bsky.richtext.facet#link",
                "uri": url
            }]
        })
    return facets

# 8. المشاركة على Bluesky
def post_to_bluesky(text_content, video_url):
    if not BLUESKY_HANDLE or not BLUESKY_PASSWORD:
        print("⚠️ تم تخطي النشر على Bluesky: متغيرات غير محددة.")
        return None, None
        
    if not video_url:
        print("⚠️ تم تخطي النشر على Bluesky: لا يوجد رابط فيديو.")
        return None, None
        
    try:
        session_res = requests.post(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            json={"identifier": BLUESKY_HANDLE, "password": BLUESKY_PASSWORD},
            timeout=15
        )
        
        if session_res.status_code != 200:
            print("❌ فشل تسجيل الدخول في Bluesky:", session_res.text)
            return None, None

        session_data = session_res.json()
        token = session_data.get("accessJwt")
        did = session_data.get("did")
        
        post_text = f"{text_content}\n\n🎬 Watch Video: {video_url}"
        facets = extract_bluesky_facets(post_text)
        
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "repo": did,
            "collection": "app.bsky.feed.post",
            "record": {
                "$type": "app.bsky.feed.post",
                "text": post_text,
                "facets": facets,
                "createdAt": datetime.utcnow().isoformat() + "Z"
            }
        }
        
        post_res = requests.post(
            "https://bsky.social/xrpc/com.atproto.repo.createRecord",
            headers=headers,
            json=payload,
            timeout=15
        )
        
        if post_res.status_code in [200, 201]:
            print("=== Shared Successfully to Bluesky (with Clickable Link)! ===")
            return token, did
        else:
            print("❌ فشل نشر التغريدة على Bluesky:", post_res.text)
            return None, None

    except Exception as e:
        print("❌ Bluesky Post Error:", e)
        return None, None

# التفاعل الخارجي على Bluesky
def engage_on_bluesky_niche(token, did, search_query):
    if not token or not search_query:
        return
        
    headers = {"Authorization": f"Bearer {token}"}
    try:
        search_url = f"https://bsky.social/xrpc/app.bsky.feed.searchPosts?q={search_query}&limit=3"
        res = requests.get(search_url, headers=headers, timeout=15).json()
        posts = res.get("posts", [])
        
        replies_pool = [
            "Totally agree! This topic is evolving so fast lately. 💡",
            "Interesting perspective! Thanks for starting this discussion. 🔥",
            "Spot on! Just covered something very similar today. 👌"
        ]
        
        for post in posts:
            post_uri = post.get("uri")
            post_cid = post.get("cid")
            
            if post.get("author", {}).get("did") == did:
                continue
                
            reply_text = random.choice(replies_pool)
            payload = {
                "repo": did,
                "collection": "app.bsky.feed.post",
                "record": {
                    "$type": "app.bsky.feed.post",
                    "text": reply_text,
                    "reply": {
                        "root": {"uri": post_uri, "cid": post_cid},
                        "parent": {"uri": post_uri, "cid": post_cid}
                    },
                    "createdAt": datetime.utcnow().isoformat() + "Z"
                }
            }
            requests.post("https://bsky.social/xrpc/com.atproto.repo.createRecord", headers=headers, json=payload, timeout=15)
            time.sleep(3)
            
        print(f"=== Engaged with {len(posts)} external posts on Bluesky! ===")
    except Exception as e:
        print("❌ Bluesky External Engagement Error:", e)

# التفاعل الخارجي على Dailymotion
def engage_on_dailymotion_niche(access_token, search_query):
    if not access_token or not search_query:
        return
        
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        search_url = f"https://api.dailymotion.com/videos?search={search_query}&fields=id,owner,title&limit=3&sort=relevance"
        res = requests.get(search_url, headers=headers, timeout=15).json()
        videos = res.get("list", [])
        
        comments_pool = [
            "Great insights! Thanks for sharing this breakdown. 👏",
            "Awesome content! Really enjoyed watching this topic. 🔥",
            "Very well explained! Keep up the great work! ✨"
        ]
        
        for vid in videos:
            vid_id = vid.get("id")
            owner_id = vid.get("owner")
            
            comment_text = random.choice(comments_pool)
            requests.post(
                f"https://api.dailymotion.com/video/{vid_id}/comments",
                headers=headers,
                data={"message": comment_text},
                timeout=15
            )
            
            if owner_id:
                requests.post(
                    f"https://api.dailymotion.com/me/following/{owner_id}",
                    headers=headers,
                    timeout=15
                )
                
            time.sleep(2)
            
        print(f"=== Engaged with {len(videos)} external Dailymotion channels in niche! ===")
    except Exception as e:
        print("❌ Dailymotion External Engagement Error:", e)

# 9. التشغيل الرئيسي
if __name__ == "__main__":
    dm_token = verify_dailymotion_auth()
    if not dm_token:
        raise Exception("إيقاف التشغيل: تعذر الاتصال بـ Dailymotion. يرجي مراجعة Secrets.")

    top_videos = fetch_top_performing_videos(dm_token)

    script_data = generate_script(top_performers=top_videos)
    asyncio.run(generate_audio_and_subtitles(script_data["script"]))
    bg_files = fetch_pexels_videos(script_data["search_queries"], script_data["orientation"])
    build_final_video(bg_files, "audio.mp3", script_data["orientation"], "final_video.mp4")
    
    video_url = upload_to_dailymotion(
        dm_token,
        "final_video.mp4",
        script_data["title"],
        script_data.get("description", script_data["title"]),
        script_data.get("tags", ["education", "facts", "shorts"]),
        script_data["playlist_name"]
    )
    
    if video_url:
        bs_token, bs_did = post_to_bluesky(script_data["bluesky_post"], video_url)
        
        main_keyword = script_data.get("search_queries", ["tech"])[0]
        
        # 1. التفاعل الخارجي على Dailymotion
        engage_on_dailymotion_niche(dm_token, main_keyword)
        
        # 2. التفاعل الخارجي على Bluesky
        if bs_token and bs_did:
            engage_on_bluesky_niche(bs_token, bs_did, main_keyword)
