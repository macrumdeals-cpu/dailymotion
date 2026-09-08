import os
import json
import random
import asyncio
import requests
import subprocess
import edge_tts
from groq import Groq
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips

# 1. التحقق من المفاتيح
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

if not GROQ_API_KEY or not PEXELS_API_KEY:
    raise ValueError("يرجى ضبط GROQ_API_KEY و PEXELS_API_KEY في إعدادات GitHub Secrets!")

# 2. توليد السكريبت بواسطة Groq مع خطاف قوي وزمن محدد (45-50 ثانية)
def generate_script():
    client = Groq(api_key=GROQ_API_KEY)
    system_prompt = """
    أنت خبير صانع فيديوهات قصيرة منتشرة (Viral Shorts).
    أنشئ نص فيديو باللغة العربية مدته بين 45 إلى 50 ثانية (حوالي 110 إلى 130 كلمة).
    الشروط الصارمة:
    1. أول 3 ثوانٍ يجب أن تبدأ بخطاف (Hook) مشوق جداً وسؤال يثير الفضول لمنع التمرير.
    2. استخدم جمل قصيرة ومباشرة مناسبة للمونتاج السريع.
    3. أرجع الناتج بصيغة JSON فقط بهذه الحقول:
       - "title": عنوان الفيديو
       - "script": النص الكامل للتعليق الصوتي
       - "search_queries": مصفوفة تحتوي على 3 كلمات مفتاحية بالإنجليزية لسحب الفيديوهات (مثل: ["dark space", "technology", "cyberpunk"])
    """
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "اكتب لي فيديو عن حقيقة مذهلة وغير معروفة عن التكنولوجيا أو المستقبل."}
        ],
        response_format={"type": "json_object"}
    )
    data = json.loads(response.choices[0].message.content)
    print("=== تم توليد السكريبت بنجاح ===")
    print("العنوان:", data.get("title"))
    return data

# 3. توليد التعليق الصوتي وملف الترجمة تلقائياً (Edge-TTS)
async def generate_audio_and_subtitles(text, audio_path="audio.mp3", srt_path="subtitles.srt"):
    voice = "ar-EG-SalmaNeural"  # صوت عربي طبيعي
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
    print("=== تم إنشاء الصوت والترجمة تلقائياً ===")

# 4. جلب فيديوهات خلفية طولية عالية الجودة من Pexels
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

# 5. المونتاج الحركي (تقطيع كل 2.5 ثانية + دموج الصوت والترجمة عبر FFmpeg)
def build_final_video(video_files, audio_path, output_path="final_video.mp4"):
    audio = AudioFileClip(audio_path)
    audio_duration = audio.duration
    
    clips = []
    clip_duration = 2.5  # تقطيع ديناميكي كل 2.5 ثانية لمنع الملل
    current_time = 0
    file_idx = 0
    
    while current_time < audio_duration:
        v_file = video_files[file_idx % len(video_files)]
        clip = VideoFileClip(v_file)
        
        # ضبط المقاسات إلى 1080x1920 (Shorts)
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
    
    # دمج النص والترجمة الأصفر/الأسود المميز في نصف الشاشة باستخدام FFmpeg
    cmd = (
        f'ffmpeg -y -i {temp_output} -vf '
        f'"subtitles=subtitles.srt:force_style=\'FontSize=20,FontName=Arial,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=2,MarginV=140\''
        f' -c:a copy {output_path}'
    )
    subprocess.run(cmd, shell=True)
    print(f"=== تم إخراج الفيديو النهائي بنجاح: {output_path} ===")

# التشغيل الرئيسي
if __name__ == "__main__":
    script_data = generate_script()
    asyncio.run(generate_audio_and_subtitles(script_data["script"]))
    bg_files = fetch_pexels_videos(script_data["search_queries"])
    build_final_video(bg_files, "audio.mp3", "final_video.mp4")
