import os
import subprocess
import glob
import math
import asyncio
import sys

# --- حل مشكلة Pyrogram مع بايثون الحديث (3.14) ---
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())
# ----------------------------------------

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# 1. إعدادات المتغيرات (هام جداً)
# ==========================================
TELEGRAM_TOKEN = "8232774943:AAFtAKRmmCLxh1rEW0ySjmfj3gmUcaKOWUM"

# تم إضافة بياناتك هنا
API_ID = 25655313
API_HASH = "25150f5a364255db770788de50a7762c"

# نفس أيدي المجلد الخاص بك
DRIVE_FOLDER_ID = '1FeRxk_jWqJnURr8u8P-YhBI18CIf8-6_' 

# ==========================================
# 2. دوال جوجل درايف (بنظام OAuth2)
# ==========================================
SERVICE_ACCOUNT_FILE = 'credentials.json'

def get_drive_service():
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(SERVICE_ACCOUNT_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    try:
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        return None

def upload_to_drive(file_path, file_name):
    service = get_drive_service()
    if not service:
        return False, "ملف credentials.json أو token.json غير موجود."
    try:
        file_metadata = {'name': file_name}
        if DRIVE_FOLDER_ID and DRIVE_FOLDER_ID != 'ضع_أيدي_المجلد_هنا':
            file_metadata['parents'] = [DRIVE_FOLDER_ID]
            
        media = MediaFileUpload(file_path, mimetype='audio/mpeg', resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        file_id = file.get('id')
        
        service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
        return True, file.get('webViewLink')
    except Exception as e:
        return False, str(e)

# ==========================================
# 3. دوال التعامل مع الصوت (FFmpeg & FFprobe)
# ==========================================
def get_audio_duration(file_path):
    command = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of",
        "default=noprint_wrappers=1:nokey=1", file_path
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return float(result.stdout.strip())

def split_audio(file_path, segment_time_seconds, output_dir="temp_audio"):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    for old_file in glob.glob(os.path.join(output_dir, "part_*.mp3")):
        try: os.remove(old_file)
        except: pass

    output_pattern = os.path.join(output_dir, "part_%03d.mp3")
    command = [
        "ffmpeg", "-y", "-i", file_path,
        "-f", "segment", "-segment_time", str(segment_time_seconds),
        output_pattern
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return sorted(glob.glob(os.path.join(output_dir, "part_*.mp3")))

# ==========================================
# 4. بوت التليجرام (باستخدام Pyrogram)
# ==========================================
app = Client(
    "audio_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=TELEGRAM_TOKEN
)

# ذاكرة لتخزين بيانات كل مستخدم مؤقتاً
user_data = {}

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("أهلاً بيك يا بطل! 🚀\nابعتلي أي ملف صوتي عشان نبدأ (بدون حدود للحجم).")

@app.on_message((filters.audio | filters.voice | filters.document) & filters.private)
async def receive_audio(client, message):
    file_id = None
    original_name = "audio.mp3"
    
    if message.audio:
        file_id = message.audio.file_id
        original_name = message.audio.file_name or "audio.mp3"
    elif message.voice:
        file_id = message.voice.file_id
        original_name = "voice.ogg"
    elif message.document:
        file_id = message.document.file_id
        original_name = message.document.file_name or "document.mp3"

    user_data[message.from_user.id] = {
        'file_id': file_id,
        'file_name': original_name,
        'step': 'CHOOSING_METHOD'
    }

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ قص بالدقائق", callback_data='by_minutes')],
        [InlineKeyboardButton("✂️ قص بعدد الأجزاء", callback_data='by_parts')]
    ])
    await message.reply_text("استلمت الملف! تحب تقصه إزاي؟", reply_markup=keyboard)

@app.on_callback_query()
async def button_callback(client, callback_query):
    user_id = callback_query.from_user.id
    choice = callback_query.data
    
    if user_id not in user_data:
        await callback_query.answer("من فضلك ابعت الملف من جديد.", show_alert=True)
        return
        
    user_data[user_id]['split_method'] = choice
    user_data[user_id]['step'] = 'TYPING_VALUE'
    
    if choice == 'by_minutes':
        text = "اكتب عدد الدقائق لكل جزء (مثلاً: 5 يعنى هيقص كل 5 دقايق):"
    else:
        text = "اكتب عدد الأجزاء اللي عاوز تقسم الملف ليها (مثلاً: 4 أجزاء متساوية):"
        
    await callback_query.message.edit_text(text)

@app.on_message(filters.text & filters.private & ~filters.command("start"))
async def process_split_and_upload(client, message):
    user_id = message.from_user.id
    
    if user_id not in user_data or user_data[user_id].get('step') != 'TYPING_VALUE':
        return
        
    try:
        value = float(message.text)
        if value <= 0: raise ValueError
    except ValueError:
        await message.reply_text("أرجوك اكتب رقم صحيح أكبر من الصفر.")
        return

    status_msg = await message.reply_text("📥 جاري تحميل الملف من تليجرام (قد يستغرق وقتاً للملفات الكبيرة)...")
    
    file_id = user_data[user_id]['file_id']
    original_name = user_data[user_id]['file_name']
    method = user_data[user_id]['split_method']
    
    if not original_name.endswith(('.mp3', '.ogg', '.wav', '.m4a')):
        original_name += ".mp3"
        
    temp_dir = "temp_audio"
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        
    # الحصول على المسار الكامل لتجنب حفظه في مسار افتراضي
    temp_file_path = os.path.abspath(os.path.join(temp_dir, original_name))
    exported_parts = []

    try:
        # 1. التحميل (بفضل Pyrogram بنقدر نحمل لحد 2 جيجا!)
        await client.download_media(file_id, file_name=temp_file_path)

        # 2. حساب وقت الجزء الواحد
        if method == 'by_minutes':
            segment_time = value * 60
        else:
            total_duration = get_audio_duration(temp_file_path)
            segment_time = math.ceil(total_duration / value) + 1

        await status_msg.edit_text("✂️ جاري قص الصوت...")

        # 3. عملية القص
        exported_parts = split_audio(temp_file_path, segment_time, output_dir=temp_dir)
        
        await status_msg.edit_text(f"☁️ تم القص لـ {len(exported_parts)} أجزاء. جاري الرفع لجوجل درايف...")

        # 4. الرفع لدرايف
        links_message = "✅ تم الانتهاء بنجاح!\n\nروابط التحميل:\n"
        safe_name = original_name.replace('.ogg', '.mp3').replace('.wav', '.mp3')
        
        for idx, part_path in enumerate(exported_parts):
            part_name = f"Part_{idx+1}_{safe_name}"
            success, result = upload_to_drive(part_path, part_name)
            
            if success:
                links_message += f"الجزء {idx+1}: {result}\n"
            else:
                links_message += f"الجزء {idx+1}: فشل الرفع ❌\nالسبب: {result}\n\n"

        await status_msg.edit_text(links_message)

    except Exception as e:
        await status_msg.edit_text(f"❌ حصلت مشكلة: {str(e)}")
    
    finally:
        # 5. تنظيف السيرفر
        if os.path.exists(temp_file_path):
            try: os.remove(temp_file_path)
            except: pass
        for part in exported_parts:
            if os.path.exists(part):
                try: os.remove(part)
                except: pass
        # مسح الذاكرة
        user_data.pop(user_id, None)

if __name__ == '__main__':
    print("🤖 البوت يعمل الآن (بنظام Pyrogram الاحترافي) وجاهز لاستقبال الملفات الضخمة...")
    app.run()
