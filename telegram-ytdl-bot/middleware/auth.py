"""
Authentication and authorization middleware
"""
import functools
from typing import Callable, Any, Optional, List
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import ChatAdminRequired
try:
    from pyrogram.errors import UserNotParticipant
except Exception:
    try:
        # Some versions use generic BadRequest with specific message; keep alias for clarity
        from pyrogram.errors import BadRequest as UserNotParticipant  # type: ignore
    except Exception:
        class UserNotParticipant(Exception):
            pass
import logging

from database.manager import db_manager
from database.models import UserStatus
from utils.cache import cache_manager
from config import settings, ERROR_MESSAGES

logger = logging.getLogger(__name__)


class AuthMiddleware:
    """Authentication middleware"""
    
    @staticmethod
    async def check_user_status(user_id: int) -> tuple[bool, Optional[str]]:
        """Check if user is allowed to use the bot"""
        # Check cache first
        cached_status = await cache_manager.hget(cache_manager.user_key(user_id), 'status')
        
        if cached_status:
            if cached_status == UserStatus.BANNED.value:
                return False, ERROR_MESSAGES['banned']
            elif cached_status == UserStatus.RESTRICTED.value:
                return False, ERROR_MESSAGES['maintenance']
        else:
            # Get from database
            user = await db_manager.get_user(user_id)
            if user:
                # Cache the status
                await cache_manager.hset(
                    cache_manager.user_key(user_id), 
                    'status', 
                    user.status.value
                )
                await cache_manager.expire(cache_manager.user_key(user_id), 300)  # 5 minutes
                
                if user.status == UserStatus.BANNED:
                    return False, ERROR_MESSAGES['banned']
                elif user.status == UserStatus.RESTRICTED:
                    return False, ERROR_MESSAGES['maintenance']
        
        return True, None
    
    @staticmethod
    async def check_channel_subscriptions(client: Client, user_id: int) -> tuple[bool, Optional[List[dict]]]:
        """Check if user is subscribed to required channels"""
        if not settings.check_subscription:
            return True, None
            
        # Get required channels from cache or database
        required_channels = await cache_manager.get('required_channels')
        if not required_channels:
            channels = await db_manager.get_required_channels()
            required_channels = [
                {
                    'id': ch.id,
                    'username': ch.username,
                    'title': ch.title
                }
                for ch in channels
            ]
            await cache_manager.set('required_channels', required_channels, 3600)  # 1 hour
        
        if not required_channels:
            return True, None
        
        # Check user subscriptions
        not_subscribed = []
        
        for channel in required_channels:
            try:
                # Check cache first
                cache_key = f"sub:{user_id}:{channel['id']}"
                is_subscribed = await cache_manager.get(cache_key)
                
                if is_subscribed is None:
                    # Check actual subscription
                    try:
                        member = await client.get_chat_member(channel['id'], user_id)
                        is_subscribed = member.status not in ['left', 'banned']
                    except UserNotParticipant:
                        is_subscribed = False
                    except ChatAdminRequired:
                        logger.error(f"Bot is not admin in channel {channel['id']}")
                        continue
                    
                    # Cache the result
                    await cache_manager.set(cache_key, is_subscribed, 300)  # 5 minutes
                
                if not is_subscribed:
                    not_subscribed.append(channel)
                    
                # Update database
                await db_manager.update_user_subscription(user_id, channel['id'], is_subscribed)
                    
            except Exception as e:
                logger.error(f"Error checking subscription for channel {channel['id']}: {e}")
                continue
        
        if not_subscribed:
            return False, not_subscribed
            
        return True, None


def require_auth(func: Callable) -> Callable:
    """Decorator to require authentication"""
    @functools.wraps(func)
    async def wrapper(client: Client, update: Any, *args, **kwargs):
        # Get user ID
        if isinstance(update, Message):
            user_id = update.from_user.id
        elif isinstance(update, CallbackQuery):
            user_id = update.from_user.id
        else:
            return
        
        # Check user status
        is_allowed, error_msg = await AuthMiddleware.check_user_status(user_id)
        if not is_allowed:
            if isinstance(update, Message):
                await update.reply_text(error_msg)
            elif isinstance(update, CallbackQuery):
                await update.answer(error_msg, show_alert=True)
            return
        
        # Check channel subscriptions
        is_subscribed, not_subscribed = await AuthMiddleware.check_channel_subscriptions(client, user_id)
        if not is_subscribed:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"📢 {ch['title'] or ch['username']}", 
                    url=f"https://t.me/{ch['username']}" if ch['username'] else f"tg://resolve?domain=c/{ch['id']}"
                )]
                for ch in not_subscribed
            ] + [[InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_subscription")]])
            
            msg = ERROR_MESSAGES['not_subscribed'] + "\n\nاشترك في القنوات التالية:"
            
            if isinstance(update, Message):
                await update.reply_text(msg, reply_markup=markup)
            elif isinstance(update, CallbackQuery):
                await update.message.reply_text(msg, reply_markup=markup)
                await update.answer()
            return
        
        # Create or update user in database
        user_data = {
            'id': user_id,
            'username': update.from_user.username,
            'first_name': update.from_user.first_name,
            'last_name': update.from_user.last_name,
            'language_code': update.from_user.language_code
        }
        await db_manager.get_or_create_user(user_data)
        
        # Track analytics
        await db_manager.create_analytics_event('user_action', user_id, {
            'action': func.__name__,
            'timestamp': datetime.utcnow().isoformat()
        })
        
        # Call the actual function
        return await func(client, update, *args, **kwargs)
    
    return wrapper


def require_admin(func: Callable) -> Callable:
    """Decorator to require admin privileges"""
    @functools.wraps(func)
    async def wrapper(client: Client, update: Any, *args, **kwargs):
        # Get user ID
        if isinstance(update, Message):
            user_id = update.from_user.id
        elif isinstance(update, CallbackQuery):
            user_id = update.from_user.id
        else:
            return
        
        # Check if user is admin
        if user_id not in settings.admin_ids:
            # Check database
            user = await db_manager.get_user(user_id)
            if not user or not user.is_admin:
                error_msg = "⛔️ هذا الأمر متاح للمشرفين فقط."
                if isinstance(update, Message):
                    await update.reply_text(error_msg)
                elif isinstance(update, CallbackQuery):
                    await update.answer(error_msg, show_alert=True)
                return
        
        # Call the actual function
        return await func(client, update, *args, **kwargs)
    
    return wrapper


def require_private(func: Callable) -> Callable:
    """Decorator to require private chat"""
    @functools.wraps(func)
    async def wrapper(client: Client, message: Message, *args, **kwargs):
        if message.chat.type != 'private':
            await message.reply_text("⚠️ هذا الأمر متاح فقط في المحادثات الخاصة.")
            return
        
        return await func(client, message, *args, **kwargs)
    
    return wrapper


def require_group(func: Callable) -> Callable:
    """Decorator to require group chat"""
    @functools.wraps(func)
    async def wrapper(client: Client, message: Message, *args, **kwargs):
        if message.chat.type not in ['group', 'supergroup']:
            await message.reply_text("⚠️ هذا الأمر متاح فقط في المجموعات.")
            return
        
        return await func(client, message, *args, **kwargs)
    
    return wrapper


class RateLimitMiddleware:
    """Rate limiting middleware"""
    
    @staticmethod
    async def check_rate_limit(user_id: int) -> tuple[bool, Optional[str]]:
        """Check if user has exceeded rate limits"""
        # Get user plan
        user = await db_manager.get_user(user_id)
        if not user:
            return True, None
        
        # Admin bypass
        if user.is_admin or user_id in settings.admin_ids:
            return True, None
        
        # Check rate limits
        result = await db_manager.check_rate_limit(user_id)
        
        if result['is_limited']:
            reset_time = result['reset_time']
            time_left = reset_time - datetime.utcnow()
            
            if time_left.total_seconds() > 3600:
                time_str = f"{int(time_left.total_seconds() / 3600)} ساعة"
            elif time_left.total_seconds() > 60:
                time_str = f"{int(time_left.total_seconds() / 60)} دقيقة"
            else:
                time_str = f"{int(time_left.total_seconds())} ثانية"
            
            return False, ERROR_MESSAGES['rate_limited'].format(time=time_str)
        
        return True, None


def rate_limit(func: Callable) -> Callable:
    """Decorator to apply rate limiting"""
    @functools.wraps(func)
    async def wrapper(client: Client, update: Any, *args, **kwargs):
        # Get user ID
        if isinstance(update, Message):
            user_id = update.from_user.id
        elif isinstance(update, CallbackQuery):
            user_id = update.from_user.id
        else:
            return
        
        # Check rate limit
        is_allowed, error_msg = await RateLimitMiddleware.check_rate_limit(user_id)
        if not is_allowed:
            if isinstance(update, Message):
                await update.reply_text(error_msg)
            elif isinstance(update, CallbackQuery):
                await update.answer(error_msg, show_alert=True)
            return
        
        # Call the actual function
        return await func(client, update, *args, **kwargs)
    
    return wrapper