"""
Callback query handlers
"""
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import logging

from middleware.auth import require_auth
from database.manager import db_manager
from services.payment import payment_service
from utils.errors import handle_errors
from config import PLANS, VIDEO_QUALITIES

logger = logging.getLogger(__name__)


@Client.on_callback_query(filters.regex("^main_menu$"))
@handle_errors
@require_auth
async def main_menu_callback(client: Client, callback: CallbackQuery):
    """Show main menu"""
    await callback.answer()
    
    user = await db_manager.get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("❌ حدث خطأ")
        return
    
    text = f"""
🏠 **القائمة الرئيسية**

👤 مرحباً {callback.from_user.first_name}!
💎 خطتك: {PLANS[user.plan]['name']}
💰 رصيدك: {user.credits} رصيد

ماذا تريد أن تفعل؟
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💎 ترقية الخطة", callback_data="show_plans"),
            InlineKeyboardButton("👤 حسابي", callback_data="my_account")
        ],
        [
            InlineKeyboardButton("🎁 دعوة الأصدقاء", callback_data="referral_menu"),
            InlineKeyboardButton("❓ المساعدة", callback_data="help")
        ],
        [
            InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings_menu")
        ]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex("^my_account$"))
@handle_errors
@require_auth
async def my_account_callback(client: Client, callback: CallbackQuery):
    """Show account info"""
    await callback.answer()
    
    user_id = callback.from_user.id
    user = await db_manager.get_user(user_id)
    
    if not user:
        await callback.message.edit_text("❌ حدث خطأ")
        return
    
    # Get statistics
    total_downloads = await db_manager.get_user_total_downloads(user_id)
    daily_downloads = await db_manager.get_user_daily_downloads(user_id)
    plan = PLANS[user.plan]
    
    text = f"""
👤 **معلومات الحساب**

🆔 **المعرف:** `{user_id}`
💎 **الخطة:** {plan['name']}
💰 **الرصيد:** {user.credits} رصيد
📊 **التحميلات اليوم:** {daily_downloads}/{plan['daily_downloads'] if plan['daily_downloads'] != -1 else '∞'}
📈 **إجمالي التحميلات:** {total_downloads}

🎁 **رمز الإحالة:** `{user.referral_code or 'غير متوفر'}`
💸 **أرباح الإحالة:** {user.referral_earnings} رصيد

📅 **تاريخ الانضمام:** {user.joined_at.strftime('%Y-%m-%d')}
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💎 ترقية الخطة", callback_data="show_plans"),
            InlineKeyboardButton("📊 الإحصائيات", callback_data="user_stats")
        ],
        [
            InlineKeyboardButton("📜 سجل التحميلات", callback_data="download_history")
        ],
        [
            InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")
        ]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex("^show_plans$"))
@handle_errors
@require_auth
async def show_plans_callback(client: Client, callback: CallbackQuery):
    """Show available plans"""
    await callback.answer()
    
    user = await db_manager.get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("❌ حدث خطأ")
        return
    
    text = "💎 **الخطط المتاحة**\n\n"
    
    for plan_key, plan in PLANS.items():
        # Plan header
        if plan_key == user.plan:
            text += f"✅ **{plan['name']} (خطتك الحالية)**\n"
        else:
            text += f"📋 **{plan['name']}**\n"
        
        # Plan details
        if plan['daily_downloads'] == -1:
            text += "• تحميلات غير محدودة يومياً\n"
        else:
            text += f"• {plan['daily_downloads']} تحميل يومياً\n"
        
        text += f"• حجم أقصى: {plan['max_file_size_mb']} MB\n"
        
        if plan['wait_time'] > 0:
            text += f"• وقت انتظار: {plan['wait_time']} ثانية\n"
        else:
            text += "• بدون وقت انتظار\n"
        
        if 'price' in plan:
            text += f"• السعر: ${plan['price']}\n"
            text += f"• الرصيد: {plan['credits']} رصيد\n"
        
        text += "\n"
    
    keyboard = payment_service.get_plans_keyboard(user.plan)
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex(r"^plan_"))
@handle_errors
@require_auth
async def select_plan_callback(client: Client, callback: CallbackQuery):
    """Handle plan selection"""
    await callback.answer()
    
    plan_key = callback.data.split('_')[1]
    
    if plan_key not in PLANS or 'price' not in PLANS[plan_key]:
        await callback.answer("❌ خطة غير صالحة", show_alert=True)
        return
    
    plan = PLANS[plan_key]
    
    text = f"""
💳 **تأكيد الشراء**

**الخطة:** {plan['name']}
**السعر:** ${plan['price']}
**الرصيد:** {plan['credits']} رصيد

**المميزات:**
    """
    
    # Add features
    if plan['daily_downloads'] == -1:
        text += "✅ تحميلات غير محدودة يومياً\n"
    else:
        text += f"✅ {plan['daily_downloads']} تحميل يومياً\n"
    
    text += f"✅ حجم أقصى {plan['max_file_size_mb']} MB\n"
    
    if plan['wait_time'] == 0:
        text += "✅ بدون وقت انتظار\n"
    
    text += f"✅ {plan['concurrent_downloads']} تحميل متزامن\n"
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"💳 دفع ${plan['price']}",
                callback_data=f"pay_{plan_key}"
            )
        ],
        [
            InlineKeyboardButton("🔙 رجوع", callback_data="show_plans")
        ]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex(r"^pay_"))
@handle_errors
@require_auth
async def process_payment_callback(client: Client, callback: CallbackQuery):
    """Process payment for plan"""
    await callback.answer()
    
    plan_key = callback.data.split('_')[1]
    
    try:
        # Create invoice
        await payment_service.create_invoice(
            callback.from_user.id,
            plan_key,
            callback.message.chat.id
        )
        
        # Delete the message
        await callback.message.delete()
        
    except Exception as e:
        await callback.answer(f"❌ خطأ: {str(e)}", show_alert=True)


@Client.on_callback_query(filters.regex("^settings_menu$"))
@handle_errors
@require_auth
async def settings_menu_callback(client: Client, callback: CallbackQuery):
    """Show settings menu"""
    await callback.answer()
    
    user = await db_manager.get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("❌ حدث خطأ")
        return
    
    settings_data = user.settings or {}
    
    text = "⚙️ **الإعدادات**\n\nاختر ما تريد تعديله:"
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🎬 الجودة: {settings_data.get('default_quality', 'best')}",
                callback_data="setting_quality"
            )
        ],
        [
            InlineKeyboardButton(
                f"🔔 الإشعارات: {'✅' if settings_data.get('notifications', True) else '❌'}",
                callback_data="setting_notifications"
            )
        ],
        [
            InlineKeyboardButton(
                f"🌐 اللغة: {settings_data.get('language', 'ar')}",
                callback_data="setting_language"
            )
        ],
        [
            InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")
        ]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex("^setting_quality$"))
@handle_errors
@require_auth
async def quality_setting_callback(client: Client, callback: CallbackQuery):
    """Change default quality setting"""
    await callback.answer()
    
    text = "🎬 **اختر الجودة الافتراضية:**"
    
    buttons = []
    for quality_key, quality_name in VIDEO_QUALITIES.items():
        buttons.append([
            InlineKeyboardButton(
                quality_name,
                callback_data=f"set_quality_{quality_key}"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton("🔙 رجوع", callback_data="settings_menu")
    ])
    
    keyboard = InlineKeyboardMarkup(buttons)
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex(r"^set_quality_"))
@handle_errors
@require_auth
async def set_quality_callback(client: Client, callback: CallbackQuery):
    """Set default quality"""
    await callback.answer()
    
    quality = callback.data.split('_', 2)[2]
    user_id = callback.from_user.id
    
    # Update user settings
    user = await db_manager.get_user(user_id)
    settings_data = user.settings or {}
    settings_data['default_quality'] = quality
    
    await db_manager.update_user(user_id, settings=settings_data)
    
    await callback.answer(f"✅ تم تغيير الجودة الافتراضية إلى {VIDEO_QUALITIES[quality]}", show_alert=True)
    
    # Go back to settings
    await settings_menu_callback(client, callback)


@Client.on_callback_query(filters.regex("^help$"))
@handle_errors
@require_auth
async def help_callback(client: Client, callback: CallbackQuery):
    """Show help text"""
    await callback.answer()
    
    help_text = """
📚 **دليل الاستخدام**

**🎥 لتحميل فيديو:**
1. أرسل رابط الفيديو
2. اختر الجودة المطلوبة
3. انتظر اكتمال التحميل

**🎵 لتحميل الصوت:**
• اختر "صوت فقط" من قائمة الجودة

**💎 الخطط:**
• مجانية: 5 تحميلات يومياً
• مدفوعة: مميزات أكثر وبدون قيود

**🎁 احصل على رصيد مجاني:**
• ادع أصدقاءك واحصل على 10 رصيد لكل صديق

**❓ للمساعدة:**
تواصل معنا: @support
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(help_text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex("^download_history$"))
@handle_errors
@require_auth
async def download_history_callback(client: Client, callback: CallbackQuery):
    """Show download history"""
    await callback.answer()
    
    user_id = callback.from_user.id
    downloads = await db_manager.get_user_downloads(user_id, limit=10)
    
    if not downloads:
        text = "📜 **سجل التحميلات**\n\nلا توجد تحميلات بعد"
    else:
        text = "📜 **آخر 10 تحميلات**\n\n"
        
        for i, download in enumerate(downloads, 1):
            text += f"{i}. {download.title or 'بدون عنوان'}\n"
            text += f"   📅 {download.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            text += f"   📊 الحالة: {download.status.value}\n\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data="my_account")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)