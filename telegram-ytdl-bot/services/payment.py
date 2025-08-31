"""
Payment and subscription service
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import logging
from pyrogram import Client
from pyrogram.types import (
    Message, CallbackQuery, LabeledPrice,
    InlineKeyboardMarkup, InlineKeyboardButton
)

from config import settings, PLANS
from database.manager import db_manager
from utils.cache import cache_manager
from utils.errors import PaymentError

logger = logging.getLogger(__name__)


class PaymentService:
    """Payment service for handling subscriptions and credits"""
    
    def __init__(self):
        self.client: Optional[Client] = None
        self.payment_callbacks = {}
        
    async def initialize(self, client: Client):
        """Initialize payment service"""
        self.client = client
        logger.info("Payment service initialized")
    
    async def create_invoice(self, user_id: int, plan_key: str, 
                           chat_id: int) -> Optional[Message]:
        """Create payment invoice"""
        if not settings.payment_provider_token:
            raise PaymentError("المدفوعات غير مفعلة حالياً")
            
        plan = PLANS.get(plan_key)
        if not plan or 'price' not in plan:
            raise PaymentError("الخطة المطلوبة غير موجودة")
        
        # Create payment record
        payment = await db_manager.create_payment(
            user_id=user_id,
            amount=plan['price'],
            currency=settings.currency,
            credits=plan['credits'],
            plan=plan_key
        )
        
        # Create invoice
        title = f"شراء {plan['name']}"
        description = self._get_plan_description(plan)
        payload = f"payment_{payment.id}_{plan_key}"
        
        prices = [
            LabeledPrice(
                label=plan['name'],
                amount=int(plan['price'] * 100)  # Convert to cents
            )
        ]
        
        # Send invoice
        try:
            invoice_msg = await self.client.send_invoice(
                chat_id=chat_id,
                title=title,
                description=description,
                payload=payload,
                provider_token=settings.payment_provider_token,
                currency=settings.currency,
                prices=prices,
                start_parameter=f"plan_{plan_key}",
                photo_url="https://i.imgur.com/YourPlanImage.png",  # Replace with actual image
                photo_size=512,
                photo_width=512,
                photo_height=512,
                need_name=True,
                need_email=True,
                need_phone_number=False,
                need_shipping_address=False,
                is_flexible=False,
                protect_content=True
            )
            
            # Store payment callback
            self.payment_callbacks[payload] = {
                'payment_id': payment.id,
                'user_id': user_id,
                'plan_key': plan_key,
                'created_at': datetime.utcnow()
            }
            
            # Cleanup old callbacks
            await self._cleanup_old_callbacks()
            
            return invoice_msg
            
        except Exception as e:
            logger.error(f"Error creating invoice: {e}")
            raise PaymentError("فشل إنشاء الفاتورة")
    
    async def process_successful_payment(self, payload: str, 
                                       transaction_id: str) -> bool:
        """Process successful payment"""
        if payload not in self.payment_callbacks:
            logger.error(f"Unknown payment payload: {payload}")
            return False
        
        callback_data = self.payment_callbacks[payload]
        payment_id = callback_data['payment_id']
        user_id = callback_data['user_id']
        plan_key = callback_data['plan_key']
        
        # Complete payment
        success = await db_manager.complete_payment(payment_id, transaction_id)
        
        if success:
            # Get plan details
            plan = PLANS[plan_key]
            
            # Update user plan
            await db_manager.update_user(user_id, plan=plan_key)
            
            # Clear user cache
            await cache_manager.delete(cache_manager.user_key(user_id))
            
            # Send confirmation
            await self._send_payment_confirmation(user_id, plan)
            
            # Track analytics
            await db_manager.create_analytics_event('payment_success', user_id, {
                'plan': plan_key,
                'amount': plan['price'],
                'credits': plan['credits']
            })
            
            # Remove callback
            del self.payment_callbacks[payload]
            
            return True
        
        return False
    
    async def add_credits(self, user_id: int, credits: int, 
                        reason: str = "manual") -> bool:
        """Add credits to user account"""
        try:
            user = await db_manager.get_user(user_id)
            if not user:
                return False
            
            # Update user credits
            new_credits = user.credits + credits
            await db_manager.update_user(user_id, credits=new_credits)
            
            # Clear cache
            await cache_manager.delete(cache_manager.user_key(user_id))
            
            # Track analytics
            await db_manager.create_analytics_event('credits_added', user_id, {
                'amount': credits,
                'reason': reason,
                'new_balance': new_credits
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding credits: {e}")
            return False
    
    async def deduct_credits(self, user_id: int, credits: int, 
                           reason: str = "download") -> bool:
        """Deduct credits from user account"""
        try:
            user = await db_manager.get_user(user_id)
            if not user or user.credits < credits:
                return False
            
            # Update user credits
            new_credits = user.credits - credits
            await db_manager.update_user(user_id, credits=new_credits)
            
            # Clear cache
            await cache_manager.delete(cache_manager.user_key(user_id))
            
            # Track analytics
            await db_manager.create_analytics_event('credits_deducted', user_id, {
                'amount': credits,
                'reason': reason,
                'new_balance': new_credits
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Error deducting credits: {e}")
            return False
    
    async def check_user_limits(self, user_id: int) -> Dict[str, Any]:
        """Check user limits based on plan"""
        user = await db_manager.get_user(user_id)
        if not user:
            return {
                'can_download': False,
                'reason': 'user_not_found'
            }
        
        plan = PLANS.get(user.plan, PLANS['free'])
        
        # Check daily downloads
        daily_downloads = await db_manager.get_user_daily_downloads(user_id)
        if plan['daily_downloads'] != -1 and daily_downloads >= plan['daily_downloads']:
            return {
                'can_download': False,
                'reason': 'daily_limit_exceeded',
                'limit': plan['daily_downloads'],
                'used': daily_downloads
            }
        
        # Check credits for paid plans
        if user.plan != 'free' and plan.get('credits'):
            if user.credits <= 0:
                return {
                    'can_download': False,
                    'reason': 'no_credits',
                    'credits': user.credits
                }
        
        # Check wait time for free plan
        if user.plan == 'free' and plan.get('wait_time'):
            # Get last download
            downloads = await db_manager.get_user_downloads(user_id, limit=1)
            if downloads:
                last_download = downloads[0]
                time_since_last = (datetime.utcnow() - last_download.created_at).total_seconds()
                if time_since_last < plan['wait_time']:
                    return {
                        'can_download': False,
                        'reason': 'wait_time',
                        'wait_seconds': int(plan['wait_time'] - time_since_last)
                    }
        
        return {
            'can_download': True,
            'plan': user.plan,
            'credits': user.credits,
            'daily_remaining': plan['daily_downloads'] - daily_downloads if plan['daily_downloads'] != -1 else -1,
            'max_file_size_mb': plan['max_file_size_mb'],
            'features': plan['features']
        }
    
    async def get_user_subscription_info(self, user_id: int) -> Dict[str, Any]:
        """Get user subscription information"""
        user = await db_manager.get_user(user_id)
        if not user:
            return {}
        
        plan = PLANS.get(user.plan, PLANS['free'])
        daily_downloads = await db_manager.get_user_daily_downloads(user_id)
        
        # Get payment history
        payments = await db_manager.get_user_payments(user_id, limit=5)
        
        return {
            'user_id': user_id,
            'current_plan': user.plan,
            'plan_name': plan['name'],
            'credits': user.credits,
            'daily_downloads_used': daily_downloads,
            'daily_downloads_limit': plan['daily_downloads'],
            'max_file_size_mb': plan['max_file_size_mb'],
            'features': plan['features'],
            'payment_history': [
                {
                    'date': p.created_at,
                    'amount': p.amount,
                    'credits': p.credits,
                    'status': p.status.value
                }
                for p in payments
            ]
        }
    
    def get_plans_keyboard(self, current_plan: str = 'free') -> InlineKeyboardMarkup:
        """Get plans selection keyboard"""
        buttons = []
        
        for plan_key, plan in PLANS.items():
            if plan_key == 'free' or 'price' not in plan:
                continue
                
            # Plan button text
            if plan_key == current_plan:
                text = f"✅ {plan['name']} (حالياً)"
            else:
                text = f"{plan['name']} - ${plan['price']}"
            
            buttons.append([
                InlineKeyboardButton(
                    text=text,
                    callback_data=f"plan_{plan_key}"
                )
            ])
        
        buttons.append([
            InlineKeyboardButton("🔙 رجوع", callback_data="back_to_menu")
        ])
        
        return InlineKeyboardMarkup(buttons)
    
    def _get_plan_description(self, plan: Dict[str, Any]) -> str:
        """Get plan description for invoice"""
        description = f"🎯 {plan['name']}\n\n"
        
        if plan['daily_downloads'] == -1:
            description += "✅ تحميلات غير محدودة يومياً\n"
        else:
            description += f"✅ {plan['daily_downloads']} تحميل يومياً\n"
        
        description += f"✅ حجم الملف الأقصى: {plan['max_file_size_mb']} MB\n"
        
        if plan['wait_time'] == 0:
            description += "✅ بدون وقت انتظار\n"
        elif plan['wait_time'] > 0:
            description += f"✅ وقت انتظار: {plan['wait_time']} ثانية\n"
        
        description += f"✅ {plan['concurrent_downloads']} تحميل متزامن\n"
        
        if plan['credits']:
            description += f"✅ {plan['credits']} رصيد\n"
        
        # Features
        feature_names = {
            'basic_download': 'تحميل أساسي',
            'audio_extract': 'استخراج الصوت',
            'playlist_support': 'دعم قوائم التشغيل',
            'no_watermark': 'بدون علامة مائية',
            'batch_download': 'تحميل متعدد',
            'custom_filename': 'تخصيص اسم الملف',
            'subtitle_download': 'تحميل الترجمة'
        }
        
        description += "\n📋 المميزات:\n"
        for feature in plan['features']:
            if feature == 'all':
                description += "• جميع المميزات\n"
            else:
                description += f"• {feature_names.get(feature, feature)}\n"
        
        return description
    
    async def _send_payment_confirmation(self, user_id: int, plan: Dict[str, Any]):
        """Send payment confirmation to user"""
        try:
            text = (
                f"✅ تم تأكيد الدفع بنجاح!\n\n"
                f"📋 **الخطة:** {plan['name']}\n"
                f"💰 **الرصيد المضاف:** {plan['credits']} رصيد\n"
                f"🎯 **المميزات:** تم تفعيل جميع مميزات الخطة\n\n"
                f"شكراً لك على الاشتراك! 🎉"
            )
            
            await self.client.send_message(user_id, text)
            
        except Exception as e:
            logger.error(f"Error sending payment confirmation: {e}")
    
    async def _cleanup_old_callbacks(self):
        """Cleanup old payment callbacks"""
        current_time = datetime.utcnow()
        to_remove = []
        
        for payload, data in self.payment_callbacks.items():
            # Remove callbacks older than 1 hour
            if (current_time - data['created_at']).total_seconds() > 3600:
                to_remove.append(payload)
        
        for payload in to_remove:
            del self.payment_callbacks[payload]


class CreditsService:
    """Service for managing user credits"""
    
    @staticmethod
    async def calculate_download_cost(file_size_mb: float, user_plan: str) -> int:
        """Calculate download cost in credits"""
        if user_plan == 'free':
            return 0  # Free plan doesn't use credits
        
        # Base cost: 1 credit per 100MB
        base_cost = max(1, int(file_size_mb / 100))
        
        # Apply multipliers based on plan
        multipliers = {
            'basic': 1.0,
            'premium': 0.8,
            'unlimited': 0.5
        }
        
        multiplier = multipliers.get(user_plan, 1.0)
        cost = int(base_cost * multiplier)
        
        return max(1, cost)  # Minimum 1 credit
    
    @staticmethod
    async def refund_credits(user_id: int, amount: int, reason: str):
        """Refund credits to user"""
        payment_service.add_credits(user_id, amount, f"refund_{reason}")


# Create global payment service instance
payment_service = PaymentService()