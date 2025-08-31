"""
Bot configuration module
"""
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field, validator
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Bot settings configuration"""
    
    # Telegram Bot Configuration
    bot_token: str = Field(..., env='BOT_TOKEN')
    api_id: int = Field(..., env='API_ID')
    api_hash: str = Field(..., env='API_HASH')
    
    # Bot Mode
    bot_mode: str = Field('polling', env='BOT_MODE')
    webhook_url: Optional[str] = Field(None, env='WEBHOOK_URL')
    webhook_port: int = Field(8443, env='WEBHOOK_PORT')
    
    # Database Configuration
    database_url: str = Field(..., env='DATABASE_URL')
    redis_url: str = Field('redis://localhost:6379/0', env='REDIS_URL')
    
    # Download Configuration
    download_dir: str = Field('/tmp/ytdl_downloads', env='DOWNLOAD_DIR')
    max_concurrent_downloads: int = Field(3, env='MAX_CONCURRENT_DOWNLOADS')
    max_file_size_mb: int = Field(2048, env='MAX_FILE_SIZE_MB')
    chunk_size_mb: int = Field(20, env='CHUNK_SIZE_MB')
    
    # Aria2 Configuration
    aria2_rpc_url: str = Field('http://localhost:6800/rpc', env='ARIA2_RPC_URL')
    aria2_secret: Optional[str] = Field(None, env='ARIA2_SECRET')
    
    # Rate Limiting
    rate_limit_per_minute: int = Field(10, env='RATE_LIMIT_PER_MINUTE')
    rate_limit_per_hour: int = Field(50, env='RATE_LIMIT_PER_HOUR')
    rate_limit_per_day: int = Field(200, env='RATE_LIMIT_PER_DAY')
    
    # Admin Configuration
    admin_ids: List[int] = Field([], env='ADMIN_IDS')
    support_chat_id: Optional[int] = Field(None, env='SUPPORT_CHAT_ID')
    
    # Channel Requirements
    required_channels: List[int] = Field([], env='REQUIRED_CHANNELS')
    check_subscription: bool = Field(True, env='CHECK_SUBSCRIPTION')
    
    # Free Plan Limits
    free_daily_downloads: int = Field(5, env='FREE_DAILY_DOWNLOADS')
    free_max_file_size_mb: int = Field(100, env='FREE_MAX_FILE_SIZE_MB')
    free_wait_time_seconds: int = Field(30, env='FREE_WAIT_TIME_SECONDS')
    
    # Payment Configuration
    payment_provider_token: Optional[str] = Field(None, env='PAYMENT_PROVIDER_TOKEN')
    currency: str = Field('USD', env='CURRENCY')
    
    # Features Toggle
    enable_analytics: bool = Field(True, env='ENABLE_ANALYTICS')
    enable_cache: bool = Field(True, env='ENABLE_CACHE')
    enable_queue: bool = Field(True, env='ENABLE_QUEUE')
    enable_affiliate: bool = Field(True, env='ENABLE_AFFILIATE')
    
    # Workers Configuration
    pyrogram_workers: int = Field(10, env='PYROGRAM_WORKERS')
    download_workers: int = Field(3, env='DOWNLOAD_WORKERS')
    upload_workers: int = Field(3, env='UPLOAD_WORKERS')
    
    @validator('admin_ids', 'required_channels', pre=True)
    def parse_comma_separated_ids(cls, v):
        if isinstance(v, str):
            return [int(id.strip()) for id in v.split(',') if id.strip()]
        return v
    
    @validator('bot_mode')
    def validate_bot_mode(cls, v):
        if v not in ['polling', 'webhook']:
            raise ValueError('bot_mode must be either "polling" or "webhook"')
        return v
    
    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024
    
    @property
    def chunk_size_bytes(self) -> int:
        return self.chunk_size_mb * 1024 * 1024
    
    @property
    def free_max_file_size_bytes(self) -> int:
        return self.free_max_file_size_mb * 1024 * 1024
    
    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'


# Create global settings instance
settings = Settings()


# Plans configuration
PLANS = {
    'free': {
        'name': 'خطة مجانية',
        'daily_downloads': settings.free_daily_downloads,
        'max_file_size_mb': settings.free_max_file_size_mb,
        'wait_time': settings.free_wait_time_seconds,
        'concurrent_downloads': 1,
        'priority': 1,
        'features': ['basic_download', 'audio_extract']
    },
    'basic': {
        'name': 'خطة أساسية',
        'price': 4.99,
        'credits': 100,
        'daily_downloads': 50,
        'max_file_size_mb': 500,
        'wait_time': 10,
        'concurrent_downloads': 2,
        'priority': 2,
        'features': ['basic_download', 'audio_extract', 'playlist_support', 'no_watermark']
    },
    'premium': {
        'name': 'خطة متميزة',
        'price': 9.99,
        'credits': 250,
        'daily_downloads': 200,
        'max_file_size_mb': 1024,
        'wait_time': 5,
        'concurrent_downloads': 3,
        'priority': 3,
        'features': ['basic_download', 'audio_extract', 'playlist_support', 'no_watermark', 
                     'batch_download', 'custom_filename', 'subtitle_download']
    },
    'unlimited': {
        'name': 'خطة غير محدودة',
        'price': 19.99,
        'credits': 1000,
        'daily_downloads': -1,  # Unlimited
        'max_file_size_mb': 2048,
        'wait_time': 0,
        'concurrent_downloads': 5,
        'priority': 4,
        'features': ['all']
    }
}

# Error messages
ERROR_MESSAGES = {
    'not_subscribed': '❌ يجب عليك الاشتراك في القنوات المطلوبة أولاً.',
    'rate_limited': '⏱ لقد تجاوزت الحد المسموح. حاول مرة أخرى بعد {time}.',
    'file_too_large': '📦 حجم الملف كبير جداً. الحد الأقصى المسموح هو {max_size} ميجابايت.',
    'invalid_url': '❌ رابط غير صالح. الرجاء إرسال رابط YouTube صحيح.',
    'download_failed': '❌ فشل التحميل. حاول مرة أخرى لاحقاً.',
    'upload_failed': '❌ فشل الرفع. حاول مرة أخرى لاحقاً.',
    'no_credits': '💳 لا يوجد لديك رصيد كافي. اشترِ المزيد من الرصيد.',
    'maintenance': '🔧 البوت قيد الصيانة حالياً. حاول مرة أخرى لاحقاً.',
    'banned': '🚫 تم حظرك من استخدام البوت.',
}

# Success messages
SUCCESS_MESSAGES = {
    'download_started': '⬇️ بدأ التحميل...',
    'upload_started': '⬆️ بدأ الرفع...',
    'download_complete': '✅ اكتمل التحميل والرفع بنجاح!',
    'credits_added': '💰 تم إضافة {credits} رصيد إلى حسابك.',
    'plan_upgraded': '🎉 تم ترقية خطتك إلى {plan_name}!',
    'referral_bonus': '🎁 حصلت على {credits} رصيد من الإحالة!',
}

# Callback data prefixes
CALLBACK_PREFIXES = {
    'download': 'dl',
    'cancel': 'cn',
    'plan': 'pl',
    'pay': 'py',
    'admin': 'ad',
    'user': 'us',
    'settings': 'st',
    'quality': 'ql',
}

# Video quality options
VIDEO_QUALITIES = {
    'best': 'أفضل جودة',
    '2160p': '4K (2160p)',
    '1440p': '2K (1440p)', 
    '1080p': 'Full HD (1080p)',
    '720p': 'HD (720p)',
    '480p': 'SD (480p)',
    '360p': 'منخفضة (360p)',
    'audio': 'صوت فقط',
}