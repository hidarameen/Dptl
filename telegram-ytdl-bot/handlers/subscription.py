"""
Channel subscription handlers
"""
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from pyrogram.errors import ChatAdminRequired
try:
    from pyrogram.errors import UserNotParticipant
except Exception:
    try:
        from pyrogram.errors import BadRequest as UserNotParticipant  # type: ignore
    except Exception:
        class UserNotParticipant(Exception):
            pass
import logging

from database.manager import db_manager
from utils.cache import cache_manager
from utils.errors import handle_errors
from config import settings

logger = logging.getLogger(__name__)


@Client.on_callback_query(filters.regex("^check_subscription$"))
@handle_errors
async def check_subscription(client: Client, callback: CallbackQuery):
    """Check user subscription to required channels"""
    await callback.answer()
    user_id = callback.from_user.id
    
    # Get required channels
    required_channels = await db_manager.get_required_channels()
    if not required_channels:
        await callback.answer("✅ لا توجد قنوات مطلوبة", show_alert=True)
        return
    
    # Check each channel
    not_subscribed = []
    newly_subscribed = []
    
    for channel in required_channels:
        try:
            # Check subscription
            member = await client.get_chat_member(channel.id, user_id)
            is_subscribed = member.status not in ['left', 'banned']
            
            # Get cached status
            cache_key = f"sub:{user_id}:{channel.id}"
            was_subscribed = await cache_manager.get(cache_key)
            
            # Update cache and database
            await cache_manager.set(cache_key, is_subscribed, 300)
            await db_manager.update_user_subscription(user_id, channel.id, is_subscribed)
            
            if not is_subscribed:
                not_subscribed.append(channel)
            elif was_subscribed is False:
                # User just subscribed
                newly_subscribed.append(channel)
                
        except UserNotParticipant:
            not_subscribed.append(channel)
        except ChatAdminRequired:
            logger.error(f"Bot is not admin in channel {channel.id}")
        except Exception as e:
            logger.error(f"Error checking subscription: {e}")
    
    # Handle results
    if not_subscribed:
        # Still not subscribed to some channels
        text = "❌ لم تشترك في جميع القنوات المطلوبة:\n\n"
        
        keyboard = []
        for channel in not_subscribed:
            text += f"• {channel.title or 'قناة'}\n"
            
            if channel.username:
                url = f"https://t.me/{channel.username}"
            else:
                url = f"tg://resolve?domain=c/{abs(channel.id)}"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"📢 {channel.title or channel.username or 'اشترك'}",
                    url=url
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton("✅ تحقق مرة أخرى", callback_data="check_subscription")
        ])
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # All subscribed
        await callback.answer("✅ شكراً لاشتراكك!", show_alert=True)
        
        # Check for affiliate rewards
        if newly_subscribed and settings.enable_affiliate:
            total_rewards = 0
            for channel in newly_subscribed:
                if channel.is_affiliate and channel.reward_credits > 0:
                    total_rewards += channel.reward_credits
            
            if total_rewards > 0:
                # Add rewards
                user = await db_manager.get_user(user_id)
                await db_manager.update_user(
                    user_id,
                    credits=user.credits + total_rewards
                )
                
                reward_text = f"""
🎉 **مبروك!**

✅ تم التحقق من اشتراكك بنجاح
🎁 حصلت على {total_rewards} رصيد كمكافأة!

يمكنك الآن استخدام البوت بدون قيود
                """
            else:
                reward_text = """
✅ **تم التحقق بنجاح!**

يمكنك الآن استخدام البوت بدون قيود
                """
        else:
            reward_text = """
✅ **تم التحقق بنجاح!**

يمكنك الآن استخدام البوت بدون قيود
            """
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
        ])
        
        await callback.message.edit_text(reward_text, reply_markup=keyboard)


@Client.on_message(filters.command("channels") & filters.private)
@handle_errors
async def show_channels(client: Client, message: Message):
    """Show required and affiliate channels"""
    # Get all channels
    channels = await db_manager.get_all_channels()
    
    if not channels:
        await message.reply_text("لا توجد قنوات متاحة حالياً")
        return
    
    text = "📋 **القنوات المتاحة**\n\n"
    
    # Required channels
    required = [ch for ch in channels if ch.is_required]
    if required:
        text += "**🔐 القنوات المطلوبة:**\n"
        for channel in required:
            text += f"• {channel.title or channel.username or 'قناة'}\n"
        text += "\n"
    
    # Affiliate channels
    affiliate = [ch for ch in channels if ch.is_affiliate and ch.reward_credits > 0]
    if affiliate:
        text += "**🎁 قنوات المكافآت:**\n"
        for channel in affiliate:
            text += f"• {channel.title or channel.username or 'قناة'} "
            text += f"(+{channel.reward_credits} رصيد)\n"
    
    # Create keyboard
    keyboard = []
    
    # Add required channels buttons
    for channel in required:
        if channel.username:
            url = f"https://t.me/{channel.username}"
        else:
            url = f"tg://resolve?domain=c/{abs(channel.id)}"
        
        keyboard.append([
            InlineKeyboardButton(
                f"🔐 {channel.title or channel.username or 'اشترك'}",
                url=url
            )
        ])
    
    # Add affiliate channels buttons
    for channel in affiliate:
        if channel.username:
            url = f"https://t.me/{channel.username}"
        else:
            url = f"tg://resolve?domain=c/{abs(channel.id)}"
        
        keyboard.append([
            InlineKeyboardButton(
                f"🎁 {channel.title or channel.username} (+{channel.reward_credits})",
                url=url
            ),
            InlineKeyboardButton(
                "💰 احصل على المكافأة",
                callback_data=f"affiliate_channel_{channel.id}"
            )
        ])
    
    if required:
        keyboard.append([
            InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_subscription")
        ])
    
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@Client.on_message(filters.command("addchannel") & filters.private)
@handle_errors
async def add_channel_command(client: Client, message: Message):
    """Add required channel (admin only)"""
    if message.from_user.id not in settings.admin_ids:
        return
    
    if len(message.command) < 2:
        await message.reply_text(
            "استخدم: /addchannel [channel_id/username] [required:true/false] [reward:0]"
        )
        return
    
    channel_input = message.command[1]
    is_required = message.command[2].lower() == 'true' if len(message.command) > 2 else True
    reward = int(message.command[3]) if len(message.command) > 3 else 0
    
    try:
        # Get channel info
        if channel_input.startswith('-'):
            chat = await client.get_chat(int(channel_input))
        else:
            chat = await client.get_chat(channel_input)
        
        # Check if bot is admin
        try:
            bot_member = await client.get_chat_member(chat.id, "me")
            if bot_member.status != 'administrator':
                await message.reply_text(
                    "❌ يجب أن يكون البوت مشرفاً في القناة أولاً"
                )
                return
        except:
            await message.reply_text(
                "❌ لا يمكن التحقق من صلاحيات البوت في القناة"
            )
            return
        
        # Add channel to database
        channel = await db_manager.add_channel(
            channel_id=chat.id,
            username=chat.username,
            title=chat.title,
            is_required=is_required,
            is_affiliate=reward > 0,
            reward_credits=reward
        )
        
        # Clear cache
        await cache_manager.delete('required_channels')
        
        text = f"""
✅ تم إضافة القناة بنجاح!

• المعرف: {chat.id}
• الاسم: {chat.title}
• المستخدم: @{chat.username or 'غير متوفر'}
• مطلوبة: {'نعم' if is_required else 'لا'}
• مكافأة: {reward} رصيد
        """
        
        await message.reply_text(text)
        
    except Exception as e:
        await message.reply_text(f"❌ خطأ: {str(e)}")


@Client.on_message(filters.command("removechannel") & filters.private)
@handle_errors
async def remove_channel_command(client: Client, message: Message):
    """Remove channel (admin only)"""
    if message.from_user.id not in settings.admin_ids:
        return
    
    if len(message.command) < 2:
        await message.reply_text("استخدم: /removechannel [channel_id]")
        return
    
    try:
        channel_id = int(message.command[1])
        
        # Remove channel
        success = await db_manager.remove_channel(channel_id)
        
        if success:
            # Clear cache
            await cache_manager.delete('required_channels')
            await message.reply_text("✅ تم حذف القناة بنجاح")
        else:
            await message.reply_text("❌ القناة غير موجودة")
            
    except ValueError:
        await message.reply_text("❌ معرف القناة غير صالح")


# Auto-check subscription for returning users
async def auto_check_subscription(client: Client, user_id: int) -> bool:
    """Automatically check user subscriptions"""
    # Get required channels
    required_channels = await cache_manager.get('required_channels')
    if not required_channels:
        channels = await db_manager.get_required_channels()
        required_channels = [
            {'id': ch.id, 'username': ch.username, 'title': ch.title}
            for ch in channels
        ]
        await cache_manager.set('required_channels', required_channels, 3600)
    
    if not required_channels:
        return True
    
    # Check each channel
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
                
                # Cache result
                await cache_manager.set(cache_key, is_subscribed, 300)
            
            if not is_subscribed:
                return False
                
        except Exception as e:
            logger.error(f"Error in auto-check subscription: {e}")
            continue
    
    return True