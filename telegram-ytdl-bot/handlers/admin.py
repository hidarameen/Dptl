"""
Admin handlers and commands
"""
import asyncio
from typing import Optional, List
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
import logging
import matplotlib.pyplot as plt
import io

from middleware.auth import require_admin
from database.manager import db_manager
from database.models import UserStatus
from utils.cache import cache_manager
from utils.errors import handle_errors
from config import settings

logger = logging.getLogger(__name__)


@Client.on_message(filters.command("admin") & filters.private)
@handle_errors
@require_admin
async def admin_panel(client: Client, message: Message):
    """Show admin panel"""
    text = """
🛡 **لوحة الإدارة**

اختر من القائمة أدناه:
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats"),
            InlineKeyboardButton("👥 المستخدمين", callback_data="admin_users")
        ],
        [
            InlineKeyboardButton("📢 رسالة جماعية", callback_data="admin_broadcast"),
            InlineKeyboardButton("💰 إدارة الرصيد", callback_data="admin_credits")
        ],
        [
            InlineKeyboardButton("📋 القنوات المطلوبة", callback_data="admin_channels"),
            InlineKeyboardButton("⚙️ الإعدادات", callback_data="admin_settings")
        ],
        [
            InlineKeyboardButton("📜 السجلات", callback_data="admin_logs"),
            InlineKeyboardButton("🔧 الصيانة", callback_data="admin_maintenance")
        ]
    ])
    
    await message.reply_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex("^admin_stats$"))
@handle_errors
@require_admin
async def admin_stats(client: Client, callback: CallbackQuery):
    """Show admin statistics"""
    await callback.answer()
    
    # Get statistics
    stats = await db_manager.get_analytics_summary(days=7)
    
    # Get current stats
    total_users = await db_manager.get_user_count()
    active_users = await db_manager.get_user_count(status=UserStatus.ACTIVE)
    premium_users = await db_manager.get_user_count(plan='premium')
    
    text = f"""
📊 **إحصائيات البوت (آخر 7 أيام)**

**👥 المستخدمين:**
• إجمالي المستخدمين: {total_users}
• المستخدمين النشطين: {active_users}
• المستخدمين المميزين: {premium_users}
• مستخدمين جدد: {stats['users']['new']}

**📥 التحميلات:**
• إجمالي التحميلات: {stats['downloads']['total']}
• التحميلات المكتملة: {stats['downloads']['completed']}
• التحميلات الفاشلة: {stats['downloads']['failed']}
• نسبة النجاح: {stats['downloads']['success_rate']:.1f}%

**💰 المدفوعات:**
• عدد المدفوعات: {stats['payments']['count']}
• إجمالي المبلغ: ${stats['payments']['total_amount']:.2f}

**🔄 النشاط:**
• المستخدمين النشطين: {stats['users']['active']}
• متوسط التحميلات/مستخدم: {stats['downloads']['total'] / stats['users']['active']:.1f} if stats['users']['active'] > 0 else 0
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈 رسم بياني", callback_data="admin_stats_chart"),
            InlineKeyboardButton("📊 تفاصيل أكثر", callback_data="admin_stats_detailed")
        ],
        [
            InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")
        ]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex("^admin_users$"))
@handle_errors
@require_admin
async def admin_users(client: Client, callback: CallbackQuery):
    """Show user management options"""
    await callback.answer()
    
    text = """
👥 **إدارة المستخدمين**

اختر الإجراء المطلوب:
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 بحث عن مستخدم", callback_data="admin_search_user"),
            InlineKeyboardButton("📋 قائمة المستخدمين", callback_data="admin_list_users")
        ],
        [
            InlineKeyboardButton("🚫 المستخدمين المحظورين", callback_data="admin_banned_users"),
            InlineKeyboardButton("💎 المستخدمين المميزين", callback_data="admin_premium_users")
        ],
        [
            InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")
        ]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_message(filters.command("ban") & filters.private)
@handle_errors
@require_admin
async def ban_user(client: Client, message: Message):
    """Ban a user"""
    if len(message.command) < 2:
        await message.reply_text("استخدم: /ban [user_id] [reason]")
        return
    
    try:
        user_id = int(message.command[1])
        reason = ' '.join(message.command[2:]) if len(message.command) > 2 else "No reason provided"
        
        # Ban user
        success = await db_manager.ban_user(user_id, reason)
        
        if success:
            # Clear cache
            await cache_manager.delete(cache_manager.user_key(user_id))
            
            # Try to notify user
            try:
                await client.send_message(
                    user_id,
                    f"🚫 تم حظرك من استخدام البوت\n"
                    f"📝 السبب: {reason}\n\n"
                    f"للتواصل: @{settings.support_chat_id}"
                )
            except:
                pass
            
            await message.reply_text(f"✅ تم حظر المستخدم {user_id}")
        else:
            await message.reply_text("❌ فشل حظر المستخدم")
            
    except ValueError:
        await message.reply_text("❌ معرف المستخدم غير صالح")


@Client.on_message(filters.command("unban") & filters.private)
@handle_errors
@require_admin
async def unban_user(client: Client, message: Message):
    """Unban a user"""
    if len(message.command) < 2:
        await message.reply_text("استخدم: /unban [user_id]")
        return
    
    try:
        user_id = int(message.command[1])
        
        # Unban user
        success = await db_manager.unban_user(user_id)
        
        if success:
            # Clear cache
            await cache_manager.delete(cache_manager.user_key(user_id))
            
            # Try to notify user
            try:
                await client.send_message(
                    user_id,
                    "✅ تم رفع الحظر عنك!\n"
                    "يمكنك الآن استخدام البوت مرة أخرى."
                )
            except:
                pass
            
            await message.reply_text(f"✅ تم رفع الحظر عن المستخدم {user_id}")
        else:
            await message.reply_text("❌ فشل رفع الحظر")
            
    except ValueError:
        await message.reply_text("❌ معرف المستخدم غير صالح")


@Client.on_message(filters.command("addcredits") & filters.private)
@handle_errors
@require_admin
async def add_credits_command(client: Client, message: Message):
    """Add credits to a user"""
    if len(message.command) < 3:
        await message.reply_text("استخدم: /addcredits [user_id] [amount]")
        return
    
    try:
        user_id = int(message.command[1])
        amount = int(message.command[2])
        
        # Add credits
        from services.payment import payment_service
        success = await payment_service.add_credits(user_id, amount, "admin_grant")
        
        if success:
            # Notify user
            try:
                await client.send_message(
                    user_id,
                    f"🎁 تم إضافة {amount} رصيد إلى حسابك!\n"
                    f"هدية من الإدارة 🎉"
                )
            except:
                pass
            
            await message.reply_text(f"✅ تم إضافة {amount} رصيد للمستخدم {user_id}")
        else:
            await message.reply_text("❌ فشل إضافة الرصيد")
            
    except ValueError:
        await message.reply_text("❌ البيانات غير صالحة")


@Client.on_callback_query(filters.regex("^admin_broadcast$"))
@handle_errors
@require_admin
async def admin_broadcast_menu(client: Client, callback: CallbackQuery):
    """Show broadcast menu"""
    await callback.answer()
    
    text = """
📢 **رسالة جماعية**

اختر نوع الرسالة:
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 رسالة نصية", callback_data="broadcast_text"),
            InlineKeyboardButton("📷 رسالة بصورة", callback_data="broadcast_photo")
        ],
        [
            InlineKeyboardButton("📹 رسالة بفيديو", callback_data="broadcast_video"),
            InlineKeyboardButton("📄 رسالة بملف", callback_data="broadcast_document")
        ],
        [
            InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")
        ]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_message(filters.command("broadcast") & filters.private & filters.reply)
@handle_errors
@require_admin
async def broadcast_message(client: Client, message: Message):
    """Broadcast a message to all users"""
    # Get the message to broadcast
    broadcast_msg = message.reply_to_message
    
    # Confirm broadcast
    total_users = await db_manager.get_user_count(status=UserStatus.ACTIVE)
    
    confirm_text = f"""
📢 **تأكيد الرسالة الجماعية**

سيتم إرسال هذه الرسالة إلى {total_users} مستخدم نشط.

هل تريد المتابعة؟
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد", callback_data=f"confirm_broadcast_{broadcast_msg.id}"),
            InlineKeyboardButton("❌ إلغاء", callback_data="cancel_broadcast")
        ]
    ])
    
    await message.reply_text(confirm_text, reply_markup=keyboard)


async def execute_broadcast(client: Client, message_id: int, admin_id: int):
    """Execute broadcast to all users"""
    try:
        # Get message to broadcast
        message = await client.get_messages(admin_id, message_id)
        
        # Create broadcast record
        broadcast = await db_manager.create_broadcast(
            text=message.text or message.caption or '',
            created_by=admin_id,
            media_type=message.media.value if message.media else None,
            media_file_id=message.photo.file_id if message.photo else 
                         message.video.file_id if message.video else
                         message.document.file_id if message.document else None
        )
        
        # Get active users
        users = await db_manager.get_all_users(status=UserStatus.ACTIVE)
        
        sent = 0
        failed = 0
        
        # Send to users in batches
        for user in users:
            try:
                # Copy message to user
                await message.copy(user.id)
                sent += 1
                
                # Update stats every 10 messages
                if sent % 10 == 0:
                    await db_manager.update_broadcast_stats(
                        broadcast.id, sent=10
                    )
                
                # Sleep to avoid flood
                await asyncio.sleep(0.05)
                
            except Exception as e:
                logger.error(f"Failed to send broadcast to {user.id}: {e}")
                failed += 1
        
        # Final update
        await db_manager.update_broadcast_stats(
            broadcast.id, 
            sent=sent % 10, 
            failed=failed
        )
        
        # Mark as completed
        await db_manager.update_broadcast(broadcast.id, completed=True)
        
        # Notify admin
        await client.send_message(
            admin_id,
            f"✅ **اكتملت الرسالة الجماعية**\n\n"
            f"📤 تم الإرسال: {sent}\n"
            f"❌ فشل: {failed}\n"
            f"📊 نسبة النجاح: {(sent / (sent + failed) * 100):.1f}%"
        )
        
    except Exception as e:
        logger.error(f"Broadcast error: {e}")
        await client.send_message(admin_id, f"❌ فشلت الرسالة الجماعية: {str(e)}")


@Client.on_callback_query(filters.regex("^admin_channels$"))
@handle_errors
@require_admin
async def admin_channels(client: Client, callback: CallbackQuery):
    """Manage required channels"""
    await callback.answer()
    
    # Get channels
    channels = await db_manager.get_required_channels()
    
    text = "📋 **القنوات المطلوبة**\n\n"
    
    if channels:
        for i, channel in enumerate(channels, 1):
            text += f"{i}. {channel.title or 'Unknown'} (@{channel.username or channel.id})\n"
            text += f"   • مطلوبة: {'✅' if channel.is_required else '❌'}\n"
            text += f"   • مكافأة الاشتراك: {channel.reward_credits} رصيد\n\n"
    else:
        text += "لا توجد قنوات مطلوبة حالياً"
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ إضافة قناة", callback_data="admin_add_channel"),
            InlineKeyboardButton("➖ حذف قناة", callback_data="admin_remove_channel")
        ],
        [
            InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")
        ]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_message(filters.command("stats") & filters.private)
@handle_errors
@require_admin
async def stats_command(client: Client, message: Message):
    """Show detailed statistics with charts"""
    status_msg = await message.reply_text("📊 جاري إعداد الإحصائيات...")
    
    try:
        # Get stats for different periods
        stats_7d = await db_manager.get_analytics_summary(days=7)
        stats_30d = await db_manager.get_analytics_summary(days=30)
        
        # Create charts
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(12, 10))
        fig.suptitle('إحصائيات البوت', fontsize=16)
        
        # Downloads chart
        downloads_data = [
            stats_7d['downloads']['completed'],
            stats_7d['downloads']['failed']
        ]
        ax1.pie(downloads_data, labels=['مكتملة', 'فاشلة'], autopct='%1.1f%%')
        ax1.set_title('التحميلات (7 أيام)')
        
        # Users chart
        users_data = [
            stats_7d['users']['new'],
            stats_7d['users']['active'] - stats_7d['users']['new']
        ]
        ax2.bar(['جدد', 'نشطين'], users_data)
        ax2.set_title('المستخدمين (7 أيام)')
        
        # Revenue chart (mock data for example)
        days = list(range(1, 8))
        revenue = [stats_7d['payments']['total_amount'] / 7] * 7
        ax3.plot(days, revenue, marker='o')
        ax3.set_title('الإيرادات اليومية')
        ax3.set_xlabel('اليوم')
        ax3.set_ylabel('المبلغ ($)')
        
        # Plans distribution
        plans_data = []
        plans_labels = []
        for plan in ['free', 'basic', 'premium', 'unlimited']:
            count = await db_manager.get_user_count(plan=plan)
            if count > 0:
                plans_data.append(count)
                plans_labels.append(plan)
        
        ax4.pie(plans_data, labels=plans_labels, autopct='%1.1f%%')
        ax4.set_title('توزيع الخطط')
        
        # Save chart
        plt.tight_layout()
        
        # Save to bytes
        img_bytes = io.BytesIO()
        plt.savefig(img_bytes, format='png', dpi=150, bbox_inches='tight')
        img_bytes.seek(0)
        plt.close()
        
        # Send chart
        await status_msg.delete()
        await message.reply_photo(
            photo=img_bytes,
            caption="📊 **إحصائيات البوت المفصلة**"
        )
        
    except Exception as e:
        logger.error(f"Error creating stats chart: {e}")
        await status_msg.edit_text("❌ فشل إنشاء الإحصائيات")