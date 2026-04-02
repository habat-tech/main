import os
import subprocess
import glob
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, 
    ContextTypes, ConversationHandler, CallbackQueryHandler
)
# تم التعديل هنا لاستخدام OAuth بدلاً من Service Account
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# 1. إعدادات المتغيرات
# ==========================================
TELEGRAM_TOKEN = "8232774943:AAFtAKRmmCLxh1rEW0ySjmfj3gmUcaKOWUM"
SERVICE_ACCOUNT_FILE = 'credentials.json'

# نفس أيدي المجلد الخاص بك الذي نسخته
DRIVE_FOLDER_ID = '1FeRxk_jWqJnURr8u8P-YhBI18CIf8-6_' 

# حالات المحادثة (States) للبوت
CHOOSING_METHOD, TYPING_VALUE = range(2)

# ==========================================
# 2. دوال جوجل درايف (بنظام OAuth2)
# ==========================================
def get_drive_service():
    """تهيئة الاتصال بجوجل درايف باستخدام حسابك الشخصي"""
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    creds = None
    
    # 1. التحقق من وجود توكن محفوظ مسبقاً (عشان البوت ميطلبش تسجيل دخول كل شوية)
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
    # 2. لو مفيش توكن، أو التوكن انتهت صلاحيته
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # سيقوم بفتح المتصفح ليطلب منك الموافقة لأول مرة فقط
            flow = InstalledAppFlow.from_client_secrets_file(SERVICE_ACCOUNT_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # حفظ التوكن للمرات القادمة
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
    try:
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"خطأ في بناء الخدمة: {e}")
        return None

def upload_to_drive(file_path, file_name):
    """رفع الملف لدرايف وإرجاع رابط التحميل أو رسالة الخطأ"""
    service = get_drive_service()
    if not service:
        return False, "ملف credentials.json غير موجود أو فشل تسجيل الدخول."
        
    try:
        # إعداد بيانات الملف وتحديد المجلد الأب (Folder ID)
        file_metadata = {'name': file_name}
        if DRIVE_FOLDER_ID and DRIVE_FOLDER_ID != 'ضع_أيدي_المجلد_هنا':
            file_metadata['parents'] = [DRIVE_FOLDER_ID]
            
        media = MediaFileUpload(file_path, mimetype='audio/mpeg', resumable=True)
        
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        file_id = file.get('id')
        
        # إعطاء صلاحية القراءة لأي شخص معاه الرابط (اختياري لأن الملف في حسابك أصلاً)
        service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        
        return True, file.get('webViewLink')
    except Exception as e:
        # إرجاع تفاصيل الخطأ القادم من جوجل لمعرفة السبب الحقيقي
        return False, str(e)

# ==========================================
# 3. دوال التعامل مع الصوت (FFmpeg & FFprobe)
# ==========================================
def get_audio_duration(file_path):
    """حساب طول الملف الصوتي بالثواني باستخدام ffprobe"""
    command = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of",
        "default=noprint_wrappers=1:nokey=1", file_path
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return float(result.stdout.strip())

def split_audio(file_path, segment_time_seconds, output_dir="temp_audio"):
    """قص الملف الصوتي بناءً على وقت محدد بالثواني لكل جزء"""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    # تنظيف المجلد
    for old_file in glob.glob(os.path.join(output_dir, "part_*.mp3")):
        try: os.remove(old_file)
        except: pass

    output_pattern = os.path.join(output_dir, "part_%03d.mp3")

    command = [
        "ffmpeg", "-y", "-i", file_path,
        "-f", "segment", "-segment_time", str(segment_time_seconds),
        output_pattern
    ]

    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise Exception(f"خطأ في القص: {e.stderr.decode('utf-8', errors='ignore')}")

    return sorted(glob.glob(os.path.join(output_dir, "part_*.mp3")))

# ==========================================
# 4. دوال بوت التليجرام (المحادثة التفاعلية)
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً بيك يا بطل! 🚀\nابعتلي أي ملف صوتي عشان نبدأ.")
    return ConversationHandler.END

async def receive_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استلام الملف الصوتي وإظهار خيارات القص"""
    audio_file = update.message.audio or update.message.voice or update.message.document
    
    if not audio_file:
        await update.message.reply_text("أرجوك ابعت ملف صوتي صالح.")
        return ConversationHandler.END

    # حفظ بيانات الملف في الذاكرة المؤقتة للمستخدم
    context.user_data['file_id'] = audio_file.file_id
    context.user_data['file_name'] = getattr(audio_file, 'file_name', f"audio_{audio_file.file_id}.mp3")

    # أزرار الاختيار
    keyboard = [
        [InlineKeyboardButton("⏱️ قص بالدقائق", callback_data='by_minutes')],
        [InlineKeyboardButton("✂️ قص بعدد الأجزاء", callback_data='by_parts')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("استلمت الملف! تحب تقصه إزاي؟", reply_markup=reply_markup)
    return CHOOSING_METHOD

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة ضغطة الزر"""
    query = update.callback_query
    await query.answer()
    
    choice = query.data
    context.user_data['split_method'] = choice
    
    if choice == 'by_minutes':
        await query.edit_message_text("اكتب عدد الدقائق لكل جزء (مثلاً: 5 يعنى هيقص كل 5 دقايق):")
    else:
        await query.edit_message_text("اكتب عدد الأجزاء اللي عاوز تقسم الملف ليها (مثلاً: 4 أجزاء متساوية):")
        
    return TYPING_VALUE

async def process_split_and_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استلام الرقم، تحميل الملف، قصه، ورفعه"""
    user_input = update.message.text
    
    try:
        value = float(user_input)
        if value <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("أرجوك اكتب رقم صحيح أكبر من الصفر.")
        return TYPING_VALUE

    status_msg = await update.message.reply_text("📥 جاري تحميل الملف من تليجرام...")
    
    file_id = context.user_data['file_id']
    original_name = context.user_data['file_name']
    method = context.user_data['split_method']
    
    if not original_name.endswith(('.mp3', '.ogg', '.wav', '.m4a')):
        original_name += ".mp3"
        
    temp_dir = "temp_audio"
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        
    temp_file_path = os.path.join(temp_dir, original_name)
    exported_parts = []

    try:
        # 1. تحميل الملف من تليجرام
        new_file = await context.bot.get_file(file_id)
        await new_file.download_to_drive(temp_file_path)

        # 2. حساب وقت الجزء الواحد (بالثواني)
        if method == 'by_minutes':
            segment_time = value * 60
        else: # by_parts
            total_duration = get_audio_duration(temp_file_path)
            # إضافة ثانية واحدة لمعالجة كسور FFmpeg وتجنب إنشاء ملف أخير صغير جداً
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
            # استلام حالة النجاح وتفاصيل الرابط أو الخطأ
            success, result = upload_to_drive(part_path, part_name)
            
            if success:
                links_message += f"الجزء {idx+1}: {result}\n"
            else:
                links_message += f"الجزء {idx+1}: فشل الرفع ❌\nالسبب المباشر: {result}\n\n"

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

    # تنظيف الذاكرة المؤقتة وإنهاء المحادثة
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء العملية"""
    await update.message.reply_text("تم إلغاء العملية. ابعت ملف جديد لو حابب.")
    context.user_data.clear()
    return ConversationHandler.END

# ==========================================
# 5. تشغيل البوت
# ==========================================
if __name__ == '__main__':
    print("🤖 البوت يعمل الآن وجاهز لاستقبال الملفات...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # إعداد المحادثة التفاعلية
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.AUDIO | filters.VOICE | filters.Document.AUDIO, receive_audio)],
        states={
            CHOOSING_METHOD: [CallbackQueryHandler(button_callback)],
            TYPING_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_split_and_upload)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    
    app.run_polling()
