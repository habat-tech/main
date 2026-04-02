# استخدام نسخة بايثون خفيفة
FROM python:3.11-slim

# تحديث النظام وتثبيت برنامج ffmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# تحديد مجلد العمل
WORKDIR /app

# نسخ ملف المكتبات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات البوت (main.py, credentials.json, token.json, audio_bot.session)
COPY . .

# أمر تشغيل البوت
CMD ["python", "main.py"]
