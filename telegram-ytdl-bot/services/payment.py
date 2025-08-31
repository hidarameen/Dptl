"""
Payment and subscription service
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import logging
from pyrogram import Client
from pyrogram.types import (
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
        
    async def initialize(self, client: Client):
        """Initialize payment service"""
        self.client = client
        logger.info("Payment service initialized")
    
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