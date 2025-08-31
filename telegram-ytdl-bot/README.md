# Telegram YouTube Downloader Bot 🎥

بوت Telegram متقدم لتحميل الفيديوهات من YouTube ومواقع أخرى مع دعم الملفات الكبيرة (2GB+) وميزات متقدمة.

## المميزات الرئيسية 🌟

### تحميل ورفع متقدم
- ✅ دعم تحميل الفيديوهات من YouTube, Twitter, Instagram, Facebook, TikTok والمزيد
- ✅ دعم الملفات الكبيرة حتى 2GB+ باستخدام تقنية chunked upload
- ✅ تحميل متوازي وسريع باستخدام yt-dlp و Aria2
- ✅ اختيار الجودة (4K, 1080p, 720p, إلخ) أو تحميل الصوت فقط
- ✅ معالجة متعددة للتحميلات في نفس الوقت

### نظام الخطط والاشتراكات
- 💎 خطة مجانية مع حدود يومية
- 💎 خطط مدفوعة متعددة مع مميزات إضافية
- 💎 نظام رصيد وعملات افتراضية
- 💎 بوابة دفع متكاملة

### نظام الإحالة والمكافآت
- 🎁 برنامج إحالة مع مكافآت للمستخدمين
- 🎁 مكافآت للاشتراك في قنوات محددة
- 🎁 نظام نقاط قابل للتحويل لرصيد

### إدارة متقدمة
- 🛡 لوحة إدارة شاملة
- 🛡 إحصائيات مفصلة مع رسوم بيانية
- 🛡 نظام رسائل جماعية
- 🛡 إدارة المستخدمين (حظر، رفع حظر، إضافة رصيد)

### أمان وأداء
- 🔒 نظام مصادقة وصلاحيات قوي
- 🔒 Rate limiting شامل
- 🔒 اشتراك إجباري في قنوات محددة
- 🔒 معالجة أخطاء متقدمة

### تقنيات متقدمة
- ⚡ دعم Webhook و Polling
- ⚡ قاعدة بيانات PostgreSQL
- ⚡ تخزين مؤقت Redis
- ⚡ معالجة غير متزامنة مع asyncio

## المتطلبات 📋

- Python 3.8+
- PostgreSQL 12+
- Redis 6+
- Aria2
- FFmpeg
- 2GB+ RAM
- معالج ثنائي النواة على الأقل

## التثبيت 🚀

### 1. استنساخ المشروع
```bash
git clone https://github.com/yourusername/telegram-ytdl-bot.git
cd telegram-ytdl-bot
```

### 2. إنشاء بيئة افتراضية
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# أو
venv\Scripts\activate  # Windows
```

### 3. تثبيت المتطلبات
```bash
pip install -r requirements.txt
```

### 4. تثبيت Aria2
```bash
# Ubuntu/Debian
sudo apt-get install aria2

# MacOS
brew install aria2

# Windows
# قم بتحميل aria2 من https://aria2.github.io/
```

### 5. إعداد قاعدة البيانات

#### PostgreSQL
```sql
CREATE DATABASE ytdl_bot;
CREATE USER ytdl_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE ytdl_bot TO ytdl_user;
```

#### Redis
```bash
# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis-server

# MacOS
brew install redis
brew services start redis
```

### 6. إعداد البوت

1. أنشئ بوت جديد من [@BotFather](https://t.me/botfather)
2. احصل على API ID و API Hash من [my.telegram.org](https://my.telegram.org)
3. انسخ ملف `.env.example` إلى `.env`:
```bash
cp .env.example .env
```

4. قم بتعديل ملف `.env` بمعلوماتك:
```env
# Telegram Bot Configuration
BOT_TOKEN=your_bot_token_here
API_ID=your_api_id_here
API_HASH=your_api_hash_here

# Database Configuration
DATABASE_URL=postgresql://ytdl_user:your_password@localhost:5432/ytdl_bot
REDIS_URL=redis://localhost:6379/0

# Admin Configuration
ADMIN_IDS=123456789,987654321  # ضع معرف حسابك هنا

# Payment Configuration (اختياري)
PAYMENT_PROVIDER_TOKEN=your_payment_token  # من @BotFather

# Other settings...
```

## التشغيل 🏃‍♂️

### تشغيل عادي
```bash
python main.py
```

### تشغيل مع systemd (Linux)
أنشئ ملف `/etc/systemd/system/ytdl-bot.service`:
```ini
[Unit]
Description=Telegram YouTube Downloader Bot
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/telegram-ytdl-bot
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

ثم:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ytdl-bot
sudo systemctl start ytdl-bot
```

### تشغيل مع Docker
```dockerfile
# Dockerfile متوفر في المشروع
docker build -t ytdl-bot .
docker run -d --name ytdl-bot --env-file .env ytdl-bot
```

## الاستخدام 💡

### للمستخدمين
1. ابدأ المحادثة مع البوت
2. أرسل رابط YouTube أو أي موقع مدعوم
3. اختر الجودة المطلوبة
4. انتظر التحميل والرفع

### للمشرفين
- `/admin` - لوحة الإدارة
- `/ban [user_id]` - حظر مستخدم
- `/unban [user_id]` - رفع الحظر
- `/addcredits [user_id] [amount]` - إضافة رصيد
- `/broadcast` - إرسال رسالة جماعية
- `/stats` - عرض الإحصائيات

## الهيكل 📁

```
telegram-ytdl-bot/
├── app/                  # تطبيق الويب (إن وجد)
├── database/            # نماذج وإدارة قاعدة البيانات
│   ├── __init__.py
│   ├── models.py       # نماذج SQLAlchemy
│   └── manager.py      # مدير قاعدة البيانات
├── handlers/           # معالجات أوامر البوت
│   ├── __init__.py
│   ├── start.py       # أوامر البداية
│   ├── download.py    # معالج التحميل
│   ├── admin.py       # أوامر الإدارة
│   ├── referral.py    # نظام الإحالة
│   ├── subscription.py # الاشتراك في القنوات
│   └── callbacks.py   # معالجات الأزرار
├── middleware/         # البرمجيات الوسيطة
│   ├── __init__.py
│   └── auth.py        # المصادقة والصلاحيات
├── services/          # خدمات البوت
│   ├── __init__.py
│   ├── downloader.py  # خدمة التحميل
│   ├── uploader.py    # خدمة الرفع
│   └── payment.py     # خدمة المدفوعات
├── utils/             # أدوات مساعدة
│   ├── __init__.py
│   ├── cache.py       # مدير Redis
│   └── errors.py      # معالج الأخطاء
├── config.py          # إعدادات البوت
├── main.py           # نقطة البداية
├── requirements.txt   # متطلبات Python
├── .env.example      # مثال على ملف البيئة
└── README.md         # هذا الملف
```

## تحسينات الأداء 🚀

### 1. تحسين قاعدة البيانات
```sql
-- إضافة فهارس للأداء
CREATE INDEX idx_downloads_user_created ON downloads(user_id, created_at);
CREATE INDEX idx_users_plan_status ON users(plan, status);
CREATE INDEX idx_analytics_event_timestamp ON analytics(event_type, timestamp);
```

### 2. تحسين Redis
```bash
# في redis.conf
maxmemory 2gb
maxmemory-policy allkeys-lru
```

### 3. تحسين Aria2
```bash
# في aria2.conf
max-concurrent-downloads=5
max-connection-per-server=16
split=16
min-split-size=1M
```

## الأمان 🔒

1. **استخدم HTTPS دائماً** للـ webhooks
2. **قم بتحديث المكتبات** بانتظام
3. **استخدم كلمات مرور قوية** لقاعدة البيانات
4. **قم بعمل نسخ احتياطية** منتظمة
5. **راقب السجلات** للأنشطة المشبوهة

## المساهمة 🤝

نرحب بالمساهمات! الرجاء:

1. Fork المشروع
2. أنشئ فرع للميزة (`git checkout -b feature/AmazingFeature`)
3. Commit التغييرات (`git commit -m 'Add some AmazingFeature'`)
4. Push إلى الفرع (`git push origin feature/AmazingFeature`)
5. افتح Pull Request

## الترخيص 📄

هذا المشروع مرخص تحت رخصة MIT - انظر ملف [LICENSE](LICENSE) للتفاصيل.

## الدعم 💬

- للمشاكل والأخطاء: افتح issue في GitHub
- للأسئلة: تواصل معنا على Telegram @support

## شكر خاص 🙏

- [Pyrogram](https://pyrogram.org/) - مكتبة Telegram
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - تحميل الفيديو
- [Aria2](https://aria2.github.io/) - تحميل متقدم
- جميع المساهمين في المشروع

---

صنع بـ ❤️ للمجتمع العربي