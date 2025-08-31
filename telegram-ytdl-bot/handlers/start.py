"""
Start command and basic handlers
"""
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
import logging

from middleware.auth import require_auth, require_private
from database.manager import db_manager
from utils.errors import handle_errors
from config import settings, PLANS

logger = logging.getLogger(__name__)


@Client.on_message(filters.command("start") & filters.private)
@handle_errors
@require_private
async def start_command(client: Client, message: Message):
    """Handle /start command"""
    user_id = message.from_user.id
    args = message.text.split()[1] if len(message.text.split()) > 1 else None
    
    # Check for referral code
    referral_code = None
    if args and args.startswith("ref_"):
        referral_code = args[4:]
    
    # Create or get user
    user_data = {
        'id': user_id,
        'username': message.from_user.username,
        'first_name': message.from_user.first_name,
        'last_name': message.from_user.last_name,
        'language_code': message.from_user.language_code
    }
    
    user = await db_manager.get_or_create_user(user_data)
    
    # Handle referral
    if referral_code and not user.referrer_id:
        await handle_referral(user_id, referral_code)
    
    # Welcome message
    welcome_text = f"""
👋 **مرحباً {message.from_user.first_name}!**

🎥 **أنا بوت تحميل الفيديوهات من YouTube والمواقع المدعومة**

📌 **كيفية الاستخدام:**
1️⃣ أرسل رابط الفيديو المراد تحميله
2️⃣ اختر الجودة المطلوبة
3️⃣ انتظر حتى يتم التحميل والرفع

💎 **خطتك الحالية:** {PLANS[user.plan]['name']}
💰 **رصيدك:** {user.credits} رصيد

🔥 **المميزات:**
• تحميل فيديوهات بجودة عالية
• دعم ملفات حتى 2GB+
• تحميل الصوت فقط
• سرعة فائقة في التحميل والرفع

⚡️ **استخدم الأوامر التالية:**
/help - عرض المساعدة
/account - معلومات حسابك
/upgrade - ترقية خطتك
/settings - الإعدادات

🎁 **احصل على رصيد مجاني من خلال دعوة أصدقائك!**
    """
    
    # Create keyboard
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💎 ترقية الخطة", callback_data="show_plans"),
            InlineKeyboardButton("👤 حسابي", callback_data="my_account")
        ],
        [
            InlineKeyboardButton("🎁 دعوة الأصدقاء", callback_data="referral"),
            InlineKeyboardButton("❓ المساعدة", callback_data="help")
        ],
        [
            InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")
        ]
    ])
    
    await message.reply_text(
        welcome_text,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )
    
    # Track analytics
    await db_manager.create_analytics_event('start_command', user_id, {
        'referral_code': referral_code,
        'is_new_user': user.joined_at == user.last_active
    })


@Client.on_message(filters.command("help") & filters.private)
@handle_errors
@require_auth
@require_private
async def help_command(client: Client, message: Message):
    """Handle /help command"""
    help_text = """
📚 **دليل الاستخدام الكامل**

**🎥 تحميل الفيديوهات:**
• أرسل رابط YouTube أو أي موقع مدعوم
• يمكنك إرسال عدة روابط دفعة واحدة
• الروابط المدعومة: YouTube, Twitter, Instagram, Facebook, TikTok والمزيد

**🎵 تحميل الصوت فقط:**
• أرسل الرابط واختر "صوت فقط" من القائمة
• سيتم استخراج الصوت بأعلى جودة ممكنة

**📋 قوائم التشغيل:**
• يمكن تحميل قوائم التشغيل الكاملة (للخطط المدفوعة)
• أرسل رابط القائمة وسيتم عرض خيارات التحميل

**⚡️ الأوامر المتاحة:**
/start - بدء استخدام البوت
/help - عرض هذه المساعدة
/account - معلومات حسابك وإحصائياتك
/upgrade - عرض الخطط المتاحة وترقية حسابك
/settings - إعدادات حسابك
/cancel - إلغاء التحميل الحالي
/history - عرض سجل التحميلات
/referral - برنامج الإحالة

**💎 الخطط والمميزات:**
• **مجانية**: 5 تحميلات يومياً، حجم أقصى 100MB
• **أساسية**: 50 تحميل يومياً، حجم أقصى 500MB
• **متميزة**: 200 تحميل يومياً، حجم أقصى 1GB
• **غير محدودة**: تحميلات لا محدودة، حجم أقصى 2GB+

**🎁 برنامج الإحالة:**
• احصل على 10 رصيد لكل صديق يشترك
• احصل على 20% من مشتريات من تدعوهم

**⚠️ ملاحظات مهمة:**
• احترم حقوق الطبع والنشر
• لا تحمل محتوى غير قانوني
• البوت للاستخدام الشخصي فقط

**🆘 الدعم:**
في حالة وجود مشاكل، تواصل مع: @{settings.support_chat_id}
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]
    ])
    
    await message.reply_text(help_text, reply_markup=keyboard)


@Client.on_message(filters.command("account") & filters.private)
@handle_errors
@require_auth
@require_private
async def account_command(client: Client, message: Message):
    """Handle /account command"""
    user_id = message.from_user.id
    
    # Get user info
    user = await db_manager.get_user(user_id)
    if not user:
        await message.reply_text("❌ حدث خطأ في جلب معلومات حسابك")
        return
    
    # Get statistics
    total_downloads = await db_manager.get_user_total_downloads(user_id)
    daily_downloads = await db_manager.get_user_daily_downloads(user_id)
    plan = PLANS[user.plan]
    
    # Format account info
    account_text = f"""
👤 **معلومات الحساب**

🆔 **المعرف:** `{user_id}`
👤 **الاسم:** {user.first_name} {user.last_name or ''}
🏷 **المستخدم:** @{user.username or 'غير محدد'}

💎 **الخطة الحالية:** {plan['name']}
💰 **الرصيد:** {user.credits} رصيد
📊 **التحميلات اليوم:** {daily_downloads}/{plan['daily_downloads'] if plan['daily_downloads'] != -1 else '∞'}
📈 **إجمالي التحميلات:** {total_downloads}

🎁 **رمز الإحالة:** `{user.referral_code or 'غير متوفر'}`
💸 **أرباح الإحالة:** {user.referral_earnings} رصيد
👥 **عدد الإحالات:** {await db_manager.get_user_referral_count(user_id)}

📅 **تاريخ الانضمام:** {user.joined_at.strftime('%Y-%m-%d')}
🕐 **آخر نشاط:** {user.last_active.strftime('%Y-%m-%d %H:%M')}
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💎 ترقية الخطة", callback_data="show_plans"),
            InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")
        ],
        [
            InlineKeyboardButton("🎁 دعوة الأصدقاء", callback_data="referral"),
            InlineKeyboardButton("📜 السجل", callback_data="history")
        ],
        [
            InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")
        ]
    ])
    
    await message.reply_text(account_text, reply_markup=keyboard)


@Client.on_message(filters.command("settings") & filters.private)
@handle_errors
@require_auth
@require_private
async def settings_command(client: Client, message: Message):
    """Handle /settings command"""
    user_id = message.from_user.id
    user = await db_manager.get_user(user_id)
    
    if not user:
        await message.reply_text("❌ حدث خطأ في جلب إعداداتك")
        return
    
    # Get current settings
    settings_data = user.settings or {}
    
    settings_text = """
⚙️ **الإعدادات**

اختر ما تريد تعديله:
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🎬 الجودة الافتراضية: {settings_data.get('default_quality', 'best')}",
                callback_data="setting_quality"
            )
        ],
        [
            InlineKeyboardButton(
                f"📝 اسم الملف: {'مخصص' if settings_data.get('custom_filename', False) else 'افتراضي'}",
                callback_data="setting_filename"
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
    
    await message.reply_text(settings_text, reply_markup=keyboard)


async def handle_referral(user_id: int, referral_code: str):
    """Handle referral registration"""
    try:
        # Find referrer
        referrer = await db_manager.get_user_by_referral_code(referral_code)
        if not referrer or referrer.id == user_id:
            return
        
        # Update user's referrer
        await db_manager.update_user(user_id, referrer_id=referrer.id)
        
        # Add bonus credits to referrer
        referral_bonus = 10
        await db_manager.update_user(
            referrer.id,
            credits=referrer.credits + referral_bonus,
            referral_earnings=referrer.referral_earnings + referral_bonus
        )
        
        # Notify referrer
        try:
            await client.send_message(
                referrer.id,
                f"🎉 مبروك! انضم صديق جديد باستخدام رمز الإحالة الخاص بك\n"
                f"💰 حصلت على {referral_bonus} رصيد!"
            )
        except:
            pass
        
        # Track analytics
        await db_manager.create_analytics_event('referral_success', user_id, {
            'referrer_id': referrer.id,
            'bonus_credits': referral_bonus
        })
        
    except Exception as e:
        logger.error(f"Error handling referral: {e}")