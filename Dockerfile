# Python 3.9 ကို အခြေခံမယ်
FROM python:3.9-slim

# ပြဿနာ၏ အဖြေ: FFmpeg (Merge လုပ်ရန်) နှင့် Node.js (Speed ကောင်းရန်) ကို Install လုပ်မယ်
RUN apt-get update && \
    apt-get install -y ffmpeg nodejs && \
    rm -rf /var/lib/apt/lists/*

# Work Directory သတ်မှတ်မယ်
WORKDIR /app

# Requirements တွေကို Install လုပ်မယ်
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ကုဒ်တွေအားလုံးကို ကူးထည့်မယ်
COPY . .

# App ကို Run မယ် (Render ရဲ့ Port ကို အလိုအလျောက် ယူပါလိမ့်မယ်)
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
