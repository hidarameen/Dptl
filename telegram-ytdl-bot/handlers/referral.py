"""
Referral system handlers
"""
import string
import random
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
import logging

from middleware.auth import require_auth, require_private
from database.manager import db_manager
from utils.errors import handle_errors
from config import settings

logger = logging.getLogger(__name__)


def generate_referral_code(length: int = 8) -> str:
    """Generate unique referral code"""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))


@Client.on_message(filters.command("referral") & filters.private)
@handle_errors
@require_auth
@require_private
async def referral_command(client: Client, message: Message):
    """Show referral program info"""
    user_id = message.from_user.id
    user = await db_manager.get_user(user_id)
    
    if not user:
        await message.reply_text("❌ حدث خطأ في جلب معلوماتك")
        return
    
    # Generate referral code if not exists
    if not user.referral_code:
        referral_code = generate_referral_code()
        await db_manager.update_user(user_id, referral_code=referral_code)
        user.referral_code = referral_code
    
    # Get referral stats
    referral_count = await db_manager.get_user_referral_count(user_id)
    total_earnings = user.referral_earnings
    
    # Create referral link
    bot_username = (await client.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start=ref_{user.referral_code}"
    
    text = f"""
🎁 **برنامج الإحالة**

شارك رابط الإحالة الخاص بك واحصل على مكافآت رائعة!

**🔗 رابط الإحالة الخاص بك:**
`{referral_link}`

**📊 إحصائياتك:**
• 👥 عدد الإحالات: {referral_count}
• 💰 إجمالي الأرباح: {total_earnings} رصيد

**🎯 نظام المكافآت:**
• 🎁 احصل على 10 رصيد لكل صديق جديد يشترك
• 💸 احصل على 20% من قيمة مشتريات من تدعوهم
• 🏆 مكافآت إضافية للإحالات الأكثر

**📌 كيفية الاستخدام:**
1. انسخ رابط الإحالة أعلاه
2. شاركه مع أصدقائك
3. احصل على المكافآت فور اشتراكهم

**💡 نصائح لزيادة أرباحك:**
• شارك الرابط في مجموعات التيليجرام
• انشره على وسائل التواصل الاجتماعي
• أخبر أصدقائك عن مميزات البوت
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📤 مشاركة الرابط", switch_inline_query=referral_link)
        ],
        [
            InlineKeyboardButton("👥 إحالاتي", callback_data="my_referrals"),
            InlineKeyboardButton("💰 سحب الأرباح", callback_data="withdraw_earnings")
        ],
        [
            InlineKeyboardButton("🏆 المتصدرين", callback_data="referral_leaderboard")
        ],
        [
            InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")
        ]
    ])
    
    await message.reply_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex("^my_referrals$"))
@handle_errors
@require_auth
async def my_referrals(client: Client, callback: CallbackQuery):
    """Show user's referrals"""
    await callback.answer()
    user_id = callback.from_user.id
    
    # Get user's referrals
    referrals = await db_manager.get_user_referrals(user_id, limit=10)
    
    if not referrals:
        text = "❌ لا توجد إحالات حتى الآن\n\n"
        text += "شارك رابط الإحالة الخاص بك للبدء في الكسب!"
    else:
        text = "👥 **إحالاتك الأخيرة**\n\n"
        
        for i, ref in enumerate(referrals, 1):
            text += f"{i}. "
            if ref.username:
                text += f"@{ref.username}"
            else:
                text += f"{ref.first_name}"
            
            text += f" - {ref.joined_at.strftime('%Y-%m-%d')}\n"
            
            # Check if referral made purchases
            payments = await db_manager.get_user_payments(ref.id)
            if payments:
                total_spent = sum(p.amount for p in payments if p.status == 'completed')
                commission = total_spent * 0.2
                text += f"   💰 عمولتك: {commission:.2f} رصيد\n"
        
        text += f"\n📊 **إجمالي الإحالات:** {await db_manager.get_user_referral_count(user_id)}"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data="referral_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex("^withdraw_earnings$"))
@handle_errors
@require_auth
async def withdraw_earnings(client: Client, callback: CallbackQuery):
    """Withdraw referral earnings"""
    await callback.answer()
    user_id = callback.from_user.id
    
    user = await db_manager.get_user(user_id)
    if not user:
        await callback.message.edit_text("❌ حدث خطأ")
        return
    
    earnings = user.referral_earnings
    
    if earnings < 50:  # Minimum withdrawal
        text = f"""
💰 **سحب الأرباح**

رصيدك الحالي: {earnings} رصيد

❌ الحد الأدنى للسحب هو 50 رصيد

استمر في دعوة الأصدقاء لزيادة أرباحك!
        """
    else:
        text = f"""
💰 **سحب الأرباح**

رصيدك المتاح للسحب: {earnings} رصيد

اختر طريقة السحب:
        """
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"💳 تحويل إلى رصيد ({earnings} رصيد)",
                    callback_data=f"convert_earnings_{earnings}"
                )
            ],
            [
                InlineKeyboardButton("🔙 رجوع", callback_data="referral_menu")
            ]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data="referral_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex(r"^convert_earnings_"))
@handle_errors
@require_auth
async def convert_earnings(client: Client, callback: CallbackQuery):
    """Convert earnings to credits"""
    await callback.answer()
    
    user_id = callback.from_user.id
    amount = int(callback.data.split('_')[2])
    
    user = await db_manager.get_user(user_id)
    if not user or user.referral_earnings < amount:
        await callback.answer("❌ رصيد غير كافي", show_alert=True)
        return
    
    # Convert earnings to credits
    new_credits = user.credits + amount
    new_earnings = user.referral_earnings - amount
    
    await db_manager.update_user(
        user_id,
        credits=new_credits,
        referral_earnings=new_earnings
    )
    
    # Track analytics
    await db_manager.create_analytics_event('earnings_converted', user_id, {
        'amount': amount,
        'new_balance': new_credits
    })
    
    await callback.answer(f"✅ تم تحويل {amount} رصيد بنجاح!", show_alert=True)
    
    text = f"""
✅ **تم التحويل بنجاح!**

💰 تم إضافة {amount} رصيد إلى حسابك
📊 رصيدك الحالي: {new_credits} رصيد
💸 الأرباح المتبقية: {new_earnings} رصيد
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex("^referral_leaderboard$"))
@handle_errors
@require_auth
async def referral_leaderboard(client: Client, callback: CallbackQuery):
    """Show referral leaderboard"""
    await callback.answer()
    
    # Get top referrers
    top_referrers = await db_manager.get_top_referrers(limit=10)
    
    text = "🏆 **قائمة المتصدرين - الإحالات**\n\n"
    
    medals = ['🥇', '🥈', '🥉']
    
    for i, (user, count) in enumerate(top_referrers):
        medal = medals[i] if i < 3 else f"{i+1}."
        
        name = f"@{user.username}" if user.username else user.first_name
        text += f"{medal} {name} - {count} إحالة\n"
        
        if i < 3:
            # Show earnings for top 3
            text += f"   💰 الأرباح: {user.referral_earnings} رصيد\n"
    
    # Check user's position
    user_id = callback.from_user.id
    user_position = await db_manager.get_user_referral_rank(user_id)
    
    if user_position and user_position > 10:
        text += f"\n📊 **موقعك:** #{user_position}"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data="referral_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex("^referral_menu$"))
@handle_errors
@require_auth
async def referral_menu(client: Client, callback: CallbackQuery):
    """Show referral menu"""
    await callback.answer()
    
    user_id = callback.from_user.id
    user = await db_manager.get_user(user_id)
    
    if not user:
        await callback.message.edit_text("❌ حدث خطأ")
        return
    
    # Get referral stats
    referral_count = await db_manager.get_user_referral_count(user_id)
    
    # Create referral link
    bot_username = (await client.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start=ref_{user.referral_code}"
    
    text = f"""
🎁 **برنامج الإحالة**

**رابط الإحالة:**
`{referral_link}`

**إحصائياتك:**
• 👥 الإحالات: {referral_count}
• 💰 الأرباح: {user.referral_earnings} رصيد
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📤 مشاركة", switch_inline_query=referral_link)
        ],
        [
            InlineKeyboardButton("👥 إحالاتي", callback_data="my_referrals"),
            InlineKeyboardButton("💰 سحب", callback_data="withdraw_earnings")
        ],
        [
            InlineKeyboardButton("🏆 المتصدرين", callback_data="referral_leaderboard")
        ],
        [
            InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")
        ]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


# Affiliate program for channel subscriptions
@Client.on_callback_query(filters.regex("^affiliate_channel_"))
@handle_errors
@require_auth
async def affiliate_channel_reward(client: Client, callback: CallbackQuery):
    """Handle affiliate channel subscription reward"""
    await callback.answer()
    
    channel_id = int(callback.data.split('_')[2])
    user_id = callback.from_user.id
    
    # Check if user already claimed this reward
    cache_key = f"affiliate_claimed:{user_id}:{channel_id}"
    if await cache_manager.get(cache_key):
        await callback.answer("✅ لقد حصلت على المكافأة مسبقاً", show_alert=True)
        return
    
    # Verify subscription
    try:
        member = await client.get_chat_member(channel_id, user_id)
        if member.status in ['left', 'banned']:
            await callback.answer("❌ يجب الاشتراك في القناة أولاً", show_alert=True)
            return
    except:
        await callback.answer("❌ حدث خطأ في التحقق", show_alert=True)
        return
    
    # Get channel info
    channel = await db_manager.get_channel(channel_id)
    if not channel or not channel.is_affiliate:
        await callback.answer("❌ هذه القناة غير مشاركة في البرنامج", show_alert=True)
        return
    
    # Add reward
    reward = channel.reward_credits
    user = await db_manager.get_user(user_id)
    
    await db_manager.update_user(
        user_id,
        credits=user.credits + reward
    )
    
    # Mark as claimed
    await cache_manager.set(cache_key, True, 86400 * 30)  # 30 days
    
    # Track analytics
    await db_manager.create_analytics_event('affiliate_reward', user_id, {
        'channel_id': channel_id,
        'reward': reward
    })
    
    await callback.answer(f"🎉 حصلت على {reward} رصيد!", show_alert=True)
    
    text = f"""
✅ **تم الحصول على المكافأة!**

🎁 حصلت على {reward} رصيد للاشتراك في القناة
💰 رصيدك الحالي: {user.credits + reward} رصيد

شكراً لدعمك! 🙏
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)