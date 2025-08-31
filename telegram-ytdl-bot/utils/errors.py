"""
Error handling utilities
"""
import logging
import traceback
from typing import Optional, Any, Dict
from datetime import datetime
from pyrogram import Client
from pyrogram.types import Message, CallbackQuery
from pyrogram.errors import (
    FloodWait, UserBlocked, UserDeactivated, ChatWriteForbidden,
    MessageNotModified, MessageIdInvalid, MessageDeleteForbidden,
    BadRequest, Unauthorized, Forbidden, NotFound,
    RPCError
)

# Compatibility alias: Some Pyrogram versions use UserIsBlocked instead of UserBlocked
try:
    from pyrogram.errors import UserIsBlocked as UserBlocked
except Exception:
    try:
        from pyrogram.errors import UserBlocked  # type: ignore
    except Exception:
        class UserBlocked(Exception):
            pass

from database.manager import db_manager
from config import settings

logger = logging.getLogger(__name__)


class BotError(Exception):
    """Base bot error class"""
    def __init__(self, message: str, user_message: Optional[str] = None):
        super().__init__(message)
        self.user_message = user_message or "حدث خطأ غير متوقع. حاول مرة أخرى لاحقاً."


class DownloadError(BotError):
    """Download related errors"""
    pass


class UploadError(BotError):
    """Upload related errors"""
    pass


class PaymentError(BotError):
    """Payment related errors"""
    pass


class ValidationError(BotError):
    """Validation errors"""
    pass


class QuotaExceededError(BotError):
    """Quota exceeded errors"""
    pass


class ErrorHandler:
    """Global error handler"""
    
    @staticmethod
    async def handle_error(
        error: Exception,
        client: Client,
        update: Optional[Any] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Handle errors globally"""
        # Get user info
        user_id = None
        if update:
            if isinstance(update, (Message, CallbackQuery)):
                user_id = update.from_user.id if update.from_user else None
        
        # Log error details
        error_id = datetime.utcnow().timestamp()
        logger.error(
            f"Error ID: {error_id}\n"
            f"User ID: {user_id}\n"
            f"Error Type: {type(error).__name__}\n"
            f"Error: {str(error)}\n"
            f"Context: {context}\n"
            f"Traceback: {traceback.format_exc()}"
        )
        
        # Track error in analytics
        await db_manager.create_analytics_event('error', user_id, {
            'error_id': error_id,
            'error_type': type(error).__name__,
            'error_message': str(error),
            'context': context or {}
        })
        
        # Handle specific Pyrogram errors
        if isinstance(error, FloodWait):
            await ErrorHandler._handle_flood_wait(error, update)
        elif isinstance(error, UserBlocked):
            await ErrorHandler._handle_user_blocked(user_id)
        elif isinstance(error, UserDeactivated):
            await ErrorHandler._handle_user_deactivated(user_id)
        elif isinstance(error, ChatWriteForbidden):
            await ErrorHandler._handle_chat_write_forbidden(update)
        elif isinstance(error, MessageNotModified):
            # Ignore this error
            return
        elif isinstance(error, (MessageIdInvalid, MessageDeleteForbidden)):
            # Log but don't notify user
            return
        elif isinstance(error, (Unauthorized, Forbidden)):
            await ErrorHandler._handle_unauthorized(update)
        elif isinstance(error, ServerError):
            await ErrorHandler._handle_server_error(update)
        elif isinstance(error, NetworkError):
            await ErrorHandler._handle_network_error(update)
        elif isinstance(error, BotError):
            await ErrorHandler._handle_bot_error(error, update)
        else:
            await ErrorHandler._handle_generic_error(error, update, error_id)
        
        # Notify admins for critical errors
        if isinstance(error, (ServerError, NetworkError)) or \
           (isinstance(error, BotError) and not isinstance(error, ValidationError)):
            await ErrorHandler._notify_admins(error, error_id, user_id, context)
    
    @staticmethod
    async def _handle_flood_wait(error: FloodWait, update: Optional[Any]) -> None:
        """Handle flood wait errors"""
        wait_time = error.value
        message = f"⏱ تم تجاوز حد الطلبات. الرجاء الانتظار {wait_time} ثانية."
        
        if update:
            if isinstance(update, Message):
                await update.reply_text(message)
            elif isinstance(update, CallbackQuery):
                await update.answer(message, show_alert=True)
    
    @staticmethod
    async def _handle_user_blocked(user_id: Optional[int]) -> None:
        """Handle user blocked bot"""
        if user_id:
            await db_manager.update_user(user_id, status='blocked')
    
    @staticmethod
    async def _handle_user_deactivated(user_id: Optional[int]) -> None:
        """Handle user deactivated"""
        if user_id:
            await db_manager.update_user(user_id, status='deactivated')
    
    @staticmethod
    async def _handle_chat_write_forbidden(update: Optional[Any]) -> None:
        """Handle chat write forbidden"""
        # Bot can't write in the chat, log it
        logger.warning(f"Chat write forbidden in chat: {update.chat.id if update and hasattr(update, 'chat') else 'Unknown'}")
    
    @staticmethod
    async def _handle_unauthorized(update: Optional[Any]) -> None:
        """Handle unauthorized errors"""
        message = "⛔️ غير مصرح لك بتنفيذ هذا الإجراء."
        
        if update:
            if isinstance(update, Message):
                await update.reply_text(message)
            elif isinstance(update, CallbackQuery):
                await update.answer(message, show_alert=True)
    
    @staticmethod
    async def _handle_server_error(update: Optional[Any]) -> None:
        """Handle server errors"""
        message = "🔧 حدث خطأ في الخادم. نعمل على حل المشكلة."
        
        if update:
            if isinstance(update, Message):
                await update.reply_text(message)
            elif isinstance(update, CallbackQuery):
                await update.answer(message, show_alert=True)
    
    @staticmethod
    async def _handle_network_error(update: Optional[Any]) -> None:
        """Handle network errors"""
        message = "🌐 حدث خطأ في الشبكة. حاول مرة أخرى لاحقاً."
        
        if update:
            if isinstance(update, Message):
                await update.reply_text(message)
            elif isinstance(update, CallbackQuery):
                await update.answer(message, show_alert=True)
    
    @staticmethod
    async def _handle_bot_error(error: BotError, update: Optional[Any]) -> None:
        """Handle custom bot errors"""
        message = error.user_message
        
        if update:
            if isinstance(update, Message):
                await update.reply_text(message)
            elif isinstance(update, CallbackQuery):
                await update.answer(message, show_alert=True)
    
    @staticmethod
    async def _handle_generic_error(error: Exception, update: Optional[Any], error_id: float) -> None:
        """Handle generic errors"""
        message = f"❌ حدث خطأ غير متوقع.\nرقم الخطأ: {int(error_id)}"
        
        if update:
            if isinstance(update, Message):
                await update.reply_text(message)
            elif isinstance(update, CallbackQuery):
                await update.answer("حدث خطأ", show_alert=True)
    
    @staticmethod
    async def _notify_admins(
        error: Exception,
        error_id: float,
        user_id: Optional[int],
        context: Optional[Dict[str, Any]]
    ) -> None:
        """Notify admins about critical errors"""
        # This would be implemented to send notifications to admin users
        # For now, just log it
        logger.critical(
            f"Critical error requiring admin attention:\n"
            f"Error ID: {error_id}\n"
            f"User ID: {user_id}\n"
            f"Error: {error}\n"
            f"Context: {context}"
        )


def handle_errors(func):
    """Decorator to handle errors in handlers"""
    async def wrapper(client: Client, update: Any, *args, **kwargs):
        try:
            return await func(client, update, *args, **kwargs)
        except Exception as e:
            context = {
                'function': func.__name__,
                'args': str(args),
                'kwargs': str(kwargs)
            }
            await ErrorHandler.handle_error(e, client, update, context)
    
    return wrapper
