"""
Download handlers
"""
import re
import asyncio
import base64
from typing import Optional, List, Dict, Any
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery, 
    InlineKeyboardMarkup, InlineKeyboardButton
)
import logging

from middleware.auth import require_auth, rate_limit
from database.manager import db_manager
from utils.cache import cache_manager
from utils.errors import handle_errors, DownloadError, ValidationError
from services.downloader import download_service
from services.uploader import upload_service
from services.payment import payment_service, CreditsService
from config import settings, PLANS, VIDEO_QUALITIES, SUCCESS_MESSAGES, ERROR_MESSAGES

logger = logging.getLogger(__name__)

# URL regex patterns
URL_PATTERNS = [
    re.compile(r'(https?://)?(www\.)?(youtube\.com|youtu\.be|m\.youtube\.com)/(watch\?v=|embed/|v/)?[\w-]+'),
    re.compile(r'(https?://)?(www\.)?(twitter\.com|x\.com)/\w+/status/\d+'),
    re.compile(r'(https?://)?(www\.)?(instagram\.com|instagr\.am)/(p|reel|tv)/[\w-]+'),
    re.compile(r'(https?://)?(www\.)?(facebook\.com|fb\.com|fb\.watch)/[\w./]+'),
    re.compile(r'(https?://)?(www\.)?(tiktok\.com|vm\.tiktok\.com)/[\w@./]+'),
    re.compile(r'(https?://)?(www\.)?(vimeo\.com)/\d+'),
    re.compile(r'(https?://)?(www\.)?(dailymotion\.com|dai\.ly)/[\w-]+'),
    re.compile(r'(https?://)?(www\.)?(reddit\.com)/r/\w+/comments/[\w/]+'),
]


def extract_urls(text: str) -> List[str]:
    """Extract URLs from text"""
    urls = []
    for pattern in URL_PATTERNS:
        matches = pattern.findall(text)
        for match in matches:
            if isinstance(match, tuple):
                url = ''.join(match)
            else:
                url = match
            
            # Add protocol if missing
            if not url.startswith('http'):
                url = 'https://' + url
            
            urls.append(url)
    
    return list(set(urls))  # Remove duplicates


@Client.on_message(filters.text & filters.private & ~filters.command([
    "start", "help", "account", "upgrade", "settings", "cancel", 
    "history", "referral", "admin", "stats"
]))
@handle_errors
@require_auth
@rate_limit
async def handle_download_request(client: Client, message: Message):
    """Handle download request from URL"""
    urls = extract_urls(message.text)
    
    if not urls:
        await message.reply_text(
            "❌ لم أتمكن من العثور على رابط صالح.\n"
            "📌 أرسل رابط YouTube أو أي موقع مدعوم."
        )
        return
    
    # Check user limits
    user_id = message.from_user.id
    limits = await payment_service.check_user_limits(user_id)
    
    if not limits['can_download']:
        if limits['reason'] == 'daily_limit_exceeded':
            text = f"❌ لقد تجاوزت الحد اليومي ({limits['limit']} تحميل)\n"
            text += "💎 قم بترقية خطتك للحصول على المزيد من التحميلات"
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("💎 ترقية الخطة", callback_data="show_plans")
            ]])
            await message.reply_text(text, reply_markup=keyboard)
        elif limits['reason'] == 'no_credits':
            text = "❌ لا يوجد لديك رصيد كافي\n"
            text += "💰 قم بشراء المزيد من الرصيد"
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("💰 شراء رصيد", callback_data="buy_credits")
            ]])
            await message.reply_text(text, reply_markup=keyboard)
        elif limits['reason'] == 'wait_time':
            text = f"⏱ يجب الانتظار {limits['wait_seconds']} ثانية قبل التحميل التالي\n"
            text += "💎 قم بترقية خطتك لإزالة وقت الانتظار"
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("💎 ترقية الخطة", callback_data="show_plans")
            ]])
            await message.reply_text(text, reply_markup=keyboard)
        return
    
    # Process each URL
    for url in urls[:3]:  # Limit to 3 URLs at once
        await process_download(client, message, url, limits)


async def process_download(client: Client, message: Message, 
                         url: str, limits: Dict[str, Any]):
    """Process single download"""
    user_id = message.from_user.id
    
    # Send initial message
    status_msg = await message.reply_text(
        "🔍 جاري الحصول على معلومات الفيديو...",
        disable_web_page_preview=True
    )
    
    try:
        # Get video info
        info = await download_service.ytdl.get_info(url)
        
        # Check if it's a playlist
        if info['is_playlist']:
            if 'playlist_support' not in limits['features']:
                await status_msg.edit_text(
                    "❌ خطتك لا تدعم تحميل قوائم التشغيل\n"
                    "💎 قم بترقية خطتك للحصول على هذه الميزة"
                )
                return
            
            # Handle playlist
            await handle_playlist_download(client, message, status_msg, url, info, limits)
            return
        
        # Check file size estimate (if available)
        estimated_size = 0
        if info['formats']:
            # Get best format size
            for fmt in info['formats']:
                if fmt.get('filesize'):
                    estimated_size = max(estimated_size, fmt['filesize'])
        
        if estimated_size > 0:
            size_mb = estimated_size / (1024 * 1024)
            if size_mb > limits['max_file_size_mb']:
                await status_msg.edit_text(
                    f"❌ حجم الملف ({size_mb:.1f} MB) يتجاوز الحد المسموح ({limits['max_file_size_mb']} MB)\n"
                    "💎 قم بترقية خطتك لتحميل ملفات أكبر"
                )
                return
        
        # Show quality selection
        await show_quality_selection(status_msg, info, url)
        
    except DownloadError as e:
        await status_msg.edit_text(str(e))
    except Exception as e:
        logger.error(f"Error processing download: {e}")
        await status_msg.edit_text(ERROR_MESSAGES['download_failed'])


async def show_quality_selection(message: Message, info: Dict[str, Any], url: str):
    """Show quality selection keyboard"""
    # Prepare info text
    text = f"📹 **{info['title']}**\n\n"
    
    if info.get('uploader'):
        text += f"👤 **القناة:** {info['uploader']}\n"
    
    if info.get('duration'):
        duration = info['duration']
        if duration > 3600:
            text += f"⏱ **المدة:** {duration // 3600}:{(duration % 3600) // 60:02d}:{duration % 60:02d}\n"
        else:
            text += f"⏱ **المدة:** {duration // 60}:{duration % 60:02d}\n"
    
    if info.get('view_count'):
        views = info['view_count']
        if views > 1000000:
            text += f"👁 **المشاهدات:** {views / 1000000:.1f}M\n"
        elif views > 1000:
            text += f"👁 **المشاهدات:** {views / 1000:.1f}K\n"
        else:
            text += f"👁 **المشاهدات:** {views}\n"
    
    text += "\n📥 **اختر الجودة المطلوبة:**"
    
    # Create quality buttons
    buttons = []
    
    # Add available video qualities
    available_qualities = []
    if info['formats']:
        for fmt in info['formats']:
            quality = fmt.get('quality')
            if quality and quality not in available_qualities:
                available_qualities.append(quality)
    
    # Sort qualities
    quality_order = ['2160p', '1440p', '1080p', '720p', '480p', '360p']
    sorted_qualities = [q for q in quality_order if q in available_qualities]
    
    # Add best quality option
    buttons.append([
        InlineKeyboardButton(
            "🎯 أفضل جودة",
            callback_data=f"dl_best_{encode_url(url)}"
        )
    ])
    
    # Add specific qualities (2 per row)
    for i in range(0, len(sorted_qualities), 2):
        row = []
        for j in range(2):
            if i + j < len(sorted_qualities):
                quality = sorted_qualities[i + j]
                row.append(InlineKeyboardButton(
                    f"📹 {quality}",
                    callback_data=f"dl_{quality}_{encode_url(url)}"
                ))
        if row:
            buttons.append(row)
    
    # Add audio only option
    buttons.append([
        InlineKeyboardButton(
            "🎵 صوت فقط (MP3)",
            callback_data=f"dl_audio_{encode_url(url)}"
        )
    ])
    
    # Add cancel button
    buttons.append([
        InlineKeyboardButton("❌ إلغاء", callback_data="cancel_download")
    ])
    
    keyboard = InlineKeyboardMarkup(buttons)
    
    # Update message
    await message.edit_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex(r"^dl_"))
@handle_errors
@require_auth
@rate_limit
async def handle_quality_selection(client: Client, callback: CallbackQuery):
    """Handle quality selection callback"""
    await callback.answer()
    
    # Parse callback data
    parts = callback.data.split('_', 2)
    if len(parts) != 3:
        await callback.message.edit_text("❌ خطأ في البيانات")
        return
    
    quality = parts[1]
    encoded_url = parts[2]
    url = decode_url(encoded_url)
    
    # Start download
    await start_download(client, callback.message, callback.from_user.id, url, quality)


async def start_download(client: Client, message: Message, 
                       user_id: int, url: str, quality: str):
    """Start the download process"""
    # Update message
    await message.edit_text(
        SUCCESS_MESSAGES['download_started'] + "\n\n" +
        "🔄 **التقدم:** 0%\n" +
        "⚡️ **السرعة:** -- MB/s\n" +
        "⏱ **الوقت المتبقي:** --:--"
    )
    
    try:
        # Add download to queue
        download_id = await download_service.add_download(
            user_id, url, quality,
            callback=lambda did, prog, speed, eta: asyncio.create_task(
                update_download_progress(message, did, prog, speed, eta)
            )
        )
        
        # Store download info in cache
        await cache_manager.hset(
            cache_manager.download_key(download_id),
            'message_id',
            message.id
        )
        
        # Wait for download to complete
        while True:
            download = await db_manager.get_download(download_id)
            if not download:
                break
                
            if download.status in ['completed', 'failed', 'cancelled']:
                break
                
            await asyncio.sleep(2)
        
        # Handle download result
        if download.status == 'completed':
            # Get downloaded file
            file_path = download_service.get_download_file(download_id)
            if file_path:
                # Calculate cost
                file_size_mb = download.file_size / (1024 * 1024)
                cost = await CreditsService.calculate_download_cost(
                    file_size_mb, 
                    (await db_manager.get_user(user_id)).plan
                )
                
                # Deduct credits if needed
                if cost > 0:
                    success = await payment_service.deduct_credits(
                        user_id, cost, "download"
                    )
                    if not success:
                        await message.edit_text(ERROR_MESSAGES['no_credits'])
                        return
                
                # Update message
                await message.edit_text(
                    SUCCESS_MESSAGES['upload_started'] + "\n\n" +
                    "📤 **جاري رفع الملف...**"
                )
                
                # Add to upload queue
                await upload_service.add_upload(
                    download_id, file_path, user_id, message,
                    callback=lambda did, prog, speed, eta: asyncio.create_task(
                        update_upload_progress(message, did, prog, speed, eta)
                    )
                )
                
                # Send completion message with video
                completion_text = (
                    SUCCESS_MESSAGES['download_complete'] + "\n\n" +
                    f"💰 **تم خصم:** {cost} رصيد" if cost > 0 else ""
                )
                
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 تحميل آخر", callback_data="download_another"),
                    InlineKeyboardButton("🏠 القائمة", callback_data="main_menu")
                ]])
                
                await message.edit_text(completion_text, reply_markup=keyboard)
            else:
                await message.edit_text("❌ لم يتم العثور على الملف المحمل")
                
        elif download.status == 'failed':
            error_text = ERROR_MESSAGES['download_failed']
            if download.error_message:
                error_text += f"\n\n💬 **السبب:** {download.error_message}"
            
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 إعادة المحاولة", 
                                   callback_data=f"retry_{download_id}"),
                InlineKeyboardButton("❌ إلغاء", callback_data="cancel_download")
            ]])
            
            await message.edit_text(error_text, reply_markup=keyboard)
            
        elif download.status == 'cancelled':
            await message.edit_text("❌ تم إلغاء التحميل")
            
    except DownloadError as e:
        await message.edit_text(str(e))
    except Exception as e:
        logger.error(f"Download error: {e}")
        await message.edit_text(ERROR_MESSAGES['download_failed'])


async def update_download_progress(message: Message, download_id: int, 
                                 percentage: float, speed: float, eta: int):
    """Update download progress message"""
    try:
        # Format progress bar
        progress_bar = create_progress_bar(percentage)
        
        # Format speed
        if speed > 1024 * 1024:
            speed_text = f"{speed / (1024 * 1024):.1f} MB/s"
        elif speed > 1024:
            speed_text = f"{speed / 1024:.1f} KB/s"
        else:
            speed_text = f"{speed:.0f} B/s"
        
        # Format ETA
        if eta > 3600:
            eta_text = f"{eta // 3600}:{(eta % 3600) // 60:02d}:{eta % 60:02d}"
        elif eta > 0:
            eta_text = f"{eta // 60}:{eta % 60:02d}"
        else:
            eta_text = "--:--"
        
        # Update message
        text = (
            f"⬇️ **جاري التحميل...**\n\n"
            f"{progress_bar} {percentage:.1f}%\n\n"
            f"⚡️ **السرعة:** {speed_text}\n"
            f"⏱ **الوقت المتبقي:** {eta_text}"
        )
        
        # Add cancel button
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_{download_id}")
        ]])
        
        await message.edit_text(text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error updating progress: {e}")


async def update_upload_progress(message: Message, download_id: int,
                               percentage: float, speed: float, eta: int):
    """Update upload progress message"""
    try:
        # Format progress bar
        progress_bar = create_progress_bar(percentage)
        
        # Format speed
        if speed > 1024 * 1024:
            speed_text = f"{speed / (1024 * 1024):.1f} MB/s"
        elif speed > 1024:
            speed_text = f"{speed / 1024:.1f} KB/s"
        else:
            speed_text = f"{speed:.0f} B/s"
        
        # Format ETA
        if eta > 3600:
            eta_text = f"{eta // 3600}:{(eta % 3600) // 60:02d}:{eta % 60:02d}"
        elif eta > 0:
            eta_text = f"{eta // 60}:{eta % 60:02d}"
        else:
            eta_text = "--:--"
        
        # Update message
        text = (
            f"⬆️ **جاري الرفع...**\n\n"
            f"{progress_bar} {percentage:.1f}%\n\n"
            f"⚡️ **السرعة:** {speed_text}\n"
            f"⏱ **الوقت المتبقي:** {eta_text}"
        )
        
        await message.edit_text(text)
        
    except Exception as e:
        logger.error(f"Error updating upload progress: {e}")


def create_progress_bar(percentage: float, length: int = 20) -> str:
    """Create progress bar string"""
    filled = int(length * percentage / 100)
    bar = '█' * filled + '░' * (length - filled)
    return f"[{bar}]"


def encode_url(url: str) -> str:
    """Encode URL for callback data"""
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip('=')


def decode_url(encoded: str) -> str:
    """Decode URL from callback data"""
    # Add padding if needed
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += '=' * padding
    return base64.urlsafe_b64decode(encoded).decode()


async def handle_playlist_download(client: Client, message: Message,
                                 status_msg: Message, url: str,
                                 info: Dict[str, Any], limits: Dict[str, Any]):
    """Handle playlist download"""
    # This would be implemented to handle playlist downloads
    await status_msg.edit_text(
        f"📋 **قائمة تشغيل:** {info['title']}\n"
        f"📹 **عدد الفيديوهات:** {info['playlist_count']}\n\n"
        "⚠️ ميزة تحميل قوائم التشغيل قيد التطوير حالياً"
    )


@Client.on_callback_query(filters.regex(r"^cancel_download$"))
@handle_errors
async def cancel_download(client: Client, callback: CallbackQuery):
    """Handle cancel download callback"""
    await callback.answer()
    await callback.message.edit_text("❌ تم إلغاء العملية")