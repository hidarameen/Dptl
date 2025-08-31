"""
Database manager for handling database operations
"""
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, update, delete, and_, or_, func, desc
from sqlalchemy.exc import IntegrityError
import logging

from .models import Base, User, Download, Payment, Channel, ChannelSubscription, RateLimit, BroadcastMessage, Analytics
from .models import UserStatus, DownloadStatus, PaymentStatus
from config import settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Database manager class"""
    
    def __init__(self):
        self.engine = None
        self.async_session = None
        
    async def initialize(self):
        """Initialize database connection"""
        # Convert database URL to async
        db_url = settings.database_url.replace('postgresql://', 'postgresql+asyncpg://')
        
        self.engine = create_async_engine(
            db_url,
            echo=False,
            pool_size=20,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
        )
        
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # Create tables
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
        logger.info("Database initialized successfully")
    
    async def close(self):
        """Close database connection"""
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connection closed")
    
    @asynccontextmanager
    async def get_session(self):
        """Get database session"""
        async with self.async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    
    # User operations
    async def get_user(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        async with self.get_session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            return result.scalar_one_or_none()
    
    async def create_user(self, user_data: Dict[str, Any]) -> User:
        """Create new user"""
        async with self.get_session() as session:
            # Generate referral code if not exists
            if 'referral_code' not in user_data:
                from handlers.referral import generate_referral_code
                user_data['referral_code'] = generate_referral_code()
                
            user = User(**user_data)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user
    
    async def update_user(self, user_id: int, **kwargs) -> Optional[User]:
        """Update user"""
        async with self.get_session() as session:
            result = await session.execute(
                update(User).where(User.id == user_id).values(**kwargs).returning(User)
            )
            await session.commit()
            return result.scalar_one_or_none()
    
    async def get_or_create_user(self, user_data: Dict[str, Any]) -> User:
        """Get or create user"""
        user = await self.get_user(user_data['id'])
        if not user:
            user = await self.create_user(user_data)
        else:
            # Update user info
            await self.update_user(
                user_data['id'],
                username=user_data.get('username'),
                first_name=user_data.get('first_name'),
                last_name=user_data.get('last_name'),
                last_active=datetime.utcnow()
            )
        return user
    
    async def get_user_by_referral_code(self, referral_code: str) -> Optional[User]:
        """Get user by referral code"""
        async with self.get_session() as session:
            result = await session.execute(
                select(User).where(User.referral_code == referral_code)
            )
            return result.scalar_one_or_none()
    
    async def ban_user(self, user_id: int, reason: Optional[str] = None) -> bool:
        """Ban user"""
        user = await self.update_user(user_id, status=UserStatus.BANNED)
        if user and reason:
            await self.create_analytics_event('user_banned', user_id, {'reason': reason})
        return user is not None
    
    async def unban_user(self, user_id: int) -> bool:
        """Unban user"""
        user = await self.update_user(user_id, status=UserStatus.ACTIVE)
        if user:
            await self.create_analytics_event('user_unbanned', user_id)
        return user is not None
    
    async def get_all_users(self, status: Optional[UserStatus] = None, 
                          plan: Optional[str] = None, 
                          limit: int = 100, 
                          offset: int = 0) -> List[User]:
        """Get all users with optional filters"""
        async with self.get_session() as session:
            query = select(User)
            
            if status:
                query = query.where(User.status == status)
            if plan:
                query = query.where(User.plan == plan)
                
            query = query.limit(limit).offset(offset)
            
            result = await session.execute(query)
            return result.scalars().all()
    
    async def get_user_count(self, status: Optional[UserStatus] = None, 
                           plan: Optional[str] = None) -> int:
        """Get user count"""
        async with self.get_session() as session:
            query = select(func.count(User.id))
            
            if status:
                query = query.where(User.status == status)
            if plan:
                query = query.where(User.plan == plan)
                
            result = await session.execute(query)
            return result.scalar()
    
    async def get_user_referrals(self, user_id: int, limit: int = 50) -> List[User]:
        """Get user's referrals"""
        async with self.get_session() as session:
            result = await session.execute(
                select(User)
                .where(User.referrer_id == user_id)
                .order_by(User.joined_at.desc())
                .limit(limit)
            )
            return result.scalars().all()
    
    async def get_user_referral_count(self, user_id: int) -> int:
        """Get user's referral count"""
        async with self.get_session() as session:
            result = await session.execute(
                select(func.count(User.id))
                .where(User.referrer_id == user_id)
            )
            return result.scalar()
    
    async def get_top_referrers(self, limit: int = 10) -> List[Tuple[User, int]]:
        """Get top referrers"""
        async with self.get_session() as session:
            # Subquery to count referrals
            referral_counts = (
                select(User.referrer_id, func.count(User.id).label('count'))
                .where(User.referrer_id.isnot(None))
                .group_by(User.referrer_id)
                .subquery()
            )
            
            # Main query
            result = await session.execute(
                select(User, referral_counts.c.count)
                .join(referral_counts, User.id == referral_counts.c.referrer_id)
                .order_by(referral_counts.c.count.desc())
                .limit(limit)
            )
            
            return result.all()
    
    async def get_user_referral_rank(self, user_id: int) -> Optional[int]:
        """Get user's referral rank"""
        async with self.get_session() as session:
            # Get all referral counts
            result = await session.execute(
                select(User.referrer_id, func.count(User.id).label('count'))
                .where(User.referrer_id.isnot(None))
                .group_by(User.referrer_id)
                .order_by(func.count(User.id).desc())
            )
            
            referral_counts = result.all()
            
            # Find user's rank
            for rank, (referrer_id, count) in enumerate(referral_counts, 1):
                if referrer_id == user_id:
                    return rank
            
            return None
    
    # Download operations
    async def create_download(self, user_id: int, url: str, **kwargs) -> Download:
        """Create new download"""
        async with self.get_session() as session:
            download = Download(
                user_id=user_id,
                url=url,
                **kwargs
            )
            session.add(download)
            await session.commit()
            await session.refresh(download)
            return download
    
    async def update_download(self, download_id: int, **kwargs) -> Optional[Download]:
        """Update download"""
        async with self.get_session() as session:
            result = await session.execute(
                update(Download).where(Download.id == download_id).values(**kwargs).returning(Download)
            )
            await session.commit()
            return result.scalar_one_or_none()
    
    async def get_download(self, download_id: int) -> Optional[Download]:
        """Get download by ID"""
        async with self.get_session() as session:
            result = await session.execute(
                select(Download).where(Download.id == download_id)
            )
            return result.scalar_one_or_none()
    
    async def get_user_downloads(self, user_id: int, 
                               status: Optional[DownloadStatus] = None,
                               limit: int = 50) -> List[Download]:
        """Get user downloads"""
        async with self.get_session() as session:
            query = select(Download).where(Download.user_id == user_id)
            
            if status:
                query = query.where(Download.status == status)
                
            query = query.order_by(Download.created_at.desc()).limit(limit)
            
            result = await session.execute(query)
            return result.scalars().all()
    
    async def get_pending_downloads(self, limit: int = 10) -> List[Download]:
        """Get pending downloads"""
        async with self.get_session() as session:
            result = await session.execute(
                select(Download)
                .where(Download.status == DownloadStatus.PENDING)
                .order_by(Download.created_at)
                .limit(limit)
            )
            return result.scalars().all()
    
    async def get_user_daily_downloads(self, user_id: int) -> int:
        """Get user's daily download count"""
        async with self.get_session() as session:
            today = datetime.utcnow().date()
            result = await session.execute(
                select(func.count(Download.id))
                .where(
                    and_(
                        Download.user_id == user_id,
                        func.date(Download.created_at) == today,
                        Download.status != DownloadStatus.FAILED
                    )
                )
            )
            return result.scalar()
    
    async def get_user_total_downloads(self, user_id: int) -> int:
        """Get user's total download count"""
        async with self.get_session() as session:
            result = await session.execute(
                select(func.count(Download.id))
                .where(
                    and_(
                        Download.user_id == user_id,
                        Download.status == DownloadStatus.COMPLETED
                    )
                )
            )
            return result.scalar()
    
    # Payment operations
    async def create_payment(self, user_id: int, amount: float, 
                           currency: str, credits: int, **kwargs) -> Payment:
        """Create new payment"""
        async with self.get_session() as session:
            payment = Payment(
                user_id=user_id,
                amount=amount,
                currency=currency,
                credits=credits,
                **kwargs
            )
            session.add(payment)
            await session.commit()
            await session.refresh(payment)
            return payment
    
    async def update_payment(self, payment_id: int, **kwargs) -> Optional[Payment]:
        """Update payment"""
        async with self.get_session() as session:
            result = await session.execute(
                update(Payment).where(Payment.id == payment_id).values(**kwargs).returning(Payment)
            )
            await session.commit()
            return result.scalar_one_or_none()
    
    async def complete_payment(self, payment_id: int, transaction_id: str) -> bool:
        """Complete payment and add credits"""
        async with self.get_session() as session:
            # Get payment
            result = await session.execute(
                select(Payment).where(Payment.id == payment_id)
            )
            payment = result.scalar_one_or_none()
            
            if not payment or payment.status != PaymentStatus.PENDING:
                return False
            
            # Update payment
            payment.status = PaymentStatus.COMPLETED
            payment.transaction_id = transaction_id
            payment.completed_at = datetime.utcnow()
            
            # Add credits to user
            await session.execute(
                update(User)
                .where(User.id == payment.user_id)
                .values(credits=User.credits + payment.credits)
            )
            
            # Update user plan if needed
            if payment.plan:
                await session.execute(
                    update(User)
                    .where(User.id == payment.user_id)
                    .values(plan=payment.plan)
                )
            
            await session.commit()
            
            # Track analytics
            await self.create_analytics_event('payment_completed', payment.user_id, {
                'amount': payment.amount,
                'credits': payment.credits,
                'plan': payment.plan
            })
            
            return True
    
    async def get_user_payments(self, user_id: int, limit: int = 10) -> List[Payment]:
        """Get user payments"""
        async with self.get_session() as session:
            result = await session.execute(
                select(Payment)
                .where(Payment.user_id == user_id)
                .order_by(Payment.created_at.desc())
                .limit(limit)
            )
            return result.scalars().all()
    
    # Channel operations
    async def get_required_channels(self) -> List[Channel]:
        """Get required channels"""
        async with self.get_session() as session:
            result = await session.execute(
                select(Channel).where(Channel.is_required == True)
            )
            return result.scalars().all()
    
    async def get_all_channels(self) -> List[Channel]:
        """Get all channels"""
        async with self.get_session() as session:
            result = await session.execute(select(Channel))
            return result.scalars().all()
    
    async def get_channel(self, channel_id: int) -> Optional[Channel]:
        """Get channel by ID"""
        async with self.get_session() as session:
            result = await session.execute(
                select(Channel).where(Channel.id == channel_id)
            )
            return result.scalar_one_or_none()
    
    async def add_channel(self, channel_id: int, **kwargs) -> Channel:
        """Add channel"""
        async with self.get_session() as session:
            channel = Channel(id=channel_id, **kwargs)
            session.add(channel)
            
            try:
                await session.commit()
                await session.refresh(channel)
                return channel
            except IntegrityError:
                # Channel already exists, update it
                await session.rollback()
                result = await session.execute(
                    update(Channel)
                    .where(Channel.id == channel_id)
                    .values(**kwargs)
                    .returning(Channel)
                )
                await session.commit()
                return result.scalar_one()
    
    async def remove_channel(self, channel_id: int) -> bool:
        """Remove channel"""
        async with self.get_session() as session:
            result = await session.execute(
                delete(Channel).where(Channel.id == channel_id)
            )
            await session.commit()
            return result.rowcount > 0
    
    async def check_user_subscriptions(self, user_id: int) -> Dict[int, bool]:
        """Check user channel subscriptions"""
        async with self.get_session() as session:
            # Get required channels
            channels_result = await session.execute(
                select(Channel).where(Channel.is_required == True)
            )
            channels = channels_result.scalars().all()
            
            # Get user subscriptions
            subs_result = await session.execute(
                select(ChannelSubscription)
                .where(
                    and_(
                        ChannelSubscription.user_id == user_id,
                        ChannelSubscription.is_active == True
                    )
                )
            )
            subscriptions = subs_result.scalars().all()
            
            # Create subscription map
            sub_map = {sub.channel_id: True for sub in subscriptions}
            
            # Check each channel
            return {channel.id: sub_map.get(channel.id, False) for channel in channels}
    
    async def update_user_subscription(self, user_id: int, channel_id: int, 
                                     is_subscribed: bool) -> None:
        """Update user channel subscription"""
        async with self.get_session() as session:
            # Check if subscription exists
            result = await session.execute(
                select(ChannelSubscription)
                .where(
                    and_(
                        ChannelSubscription.user_id == user_id,
                        ChannelSubscription.channel_id == channel_id
                    )
                )
            )
            subscription = result.scalar_one_or_none()
            
            if subscription:
                # Update existing
                subscription.is_active = is_subscribed
                subscription.last_checked = datetime.utcnow()
            else:
                # Create new
                subscription = ChannelSubscription(
                    user_id=user_id,
                    channel_id=channel_id,
                    is_active=is_subscribed
                )
                session.add(subscription)
            
            await session.commit()
    
    # Rate limiting operations
    async def check_rate_limit(self, user_id: int) -> Dict[str, Any]:
        """Check user rate limits"""
        async with self.get_session() as session:
            # Get or create rate limit record
            result = await session.execute(
                select(RateLimit).where(RateLimit.user_id == user_id)
            )
            rate_limit = result.scalar_one_or_none()
            
            if not rate_limit:
                rate_limit = RateLimit(user_id=user_id)
                session.add(rate_limit)
                await session.commit()
                await session.refresh(rate_limit)
            
            now = datetime.utcnow()
            
            # Reset counters if needed
            if now - rate_limit.minute_reset > timedelta(minutes=1):
                rate_limit.minute_count = 0
                rate_limit.minute_reset = now
                
            if now - rate_limit.hour_reset > timedelta(hours=1):
                rate_limit.hour_count = 0
                rate_limit.hour_reset = now
                
            if now - rate_limit.day_reset > timedelta(days=1):
                rate_limit.day_count = 0
                rate_limit.day_reset = now
            
            # Check limits
            is_limited = False
            reset_time = None
            
            if rate_limit.minute_count >= settings.rate_limit_per_minute:
                is_limited = True
                reset_time = rate_limit.minute_reset + timedelta(minutes=1)
            elif rate_limit.hour_count >= settings.rate_limit_per_hour:
                is_limited = True
                reset_time = rate_limit.hour_reset + timedelta(hours=1)
            elif rate_limit.day_count >= settings.rate_limit_per_day:
                is_limited = True
                reset_time = rate_limit.day_reset + timedelta(days=1)
            
            if not is_limited:
                # Increment counters
                rate_limit.minute_count += 1
                rate_limit.hour_count += 1
                rate_limit.day_count += 1
                rate_limit.last_action = now
                await session.commit()
            
            return {
                'is_limited': is_limited,
                'reset_time': reset_time,
                'minute_count': rate_limit.minute_count,
                'hour_count': rate_limit.hour_count,
                'day_count': rate_limit.day_count
            }
    
    # Broadcast operations
    async def create_broadcast(self, text: str, created_by: int, **kwargs) -> BroadcastMessage:
        """Create broadcast message"""
        async with self.get_session() as session:
            broadcast = BroadcastMessage(
                text=text,
                created_by=created_by,
                **kwargs
            )
            session.add(broadcast)
            await session.commit()
            await session.refresh(broadcast)
            return broadcast
    
    async def update_broadcast_stats(self, broadcast_id: int, 
                                   sent: int = 0, failed: int = 0) -> None:
        """Update broadcast statistics"""
        async with self.get_session() as session:
            await session.execute(
                update(BroadcastMessage)
                .where(BroadcastMessage.id == broadcast_id)
                .values(
                    sent_count=BroadcastMessage.sent_count + sent,
                    failed_count=BroadcastMessage.failed_count + failed
                )
            )
            await session.commit()
    
    async def update_broadcast(self, broadcast_id: int, **kwargs) -> None:
        """Update broadcast"""
        async with self.get_session() as session:
            await session.execute(
                update(BroadcastMessage)
                .where(BroadcastMessage.id == broadcast_id)
                .values(**kwargs)
            )
            await session.commit()
    
    # Analytics operations
    async def create_analytics_event(self, event_type: str, 
                                   user_id: Optional[int] = None,
                                   data: Optional[Dict[str, Any]] = None) -> None:
        """Create analytics event"""
        if not settings.enable_analytics:
            return
            
        async with self.get_session() as session:
            event = Analytics(
                event_type=event_type,
                user_id=user_id,
                data=data or {}
            )
            session.add(event)
            await session.commit()
    
    async def get_analytics_summary(self, days: int = 7) -> Dict[str, Any]:
        """Get analytics summary"""
        async with self.get_session() as session:
            since = datetime.utcnow() - timedelta(days=days)
            
            # Download stats
            download_stats = await session.execute(
                select(
                    func.count(Download.id).label('total'),
                    func.count(Download.id).filter(Download.status == DownloadStatus.COMPLETED).label('completed'),
                    func.count(Download.id).filter(Download.status == DownloadStatus.FAILED).label('failed')
                ).where(Download.created_at >= since)
            )
            downloads = download_stats.first()
            
            # User stats
            user_stats = await session.execute(
                select(
                    func.count(User.id).label('total'),
                    func.count(User.id).filter(User.joined_at >= since).label('new'),
                    func.count(User.id).filter(User.last_active >= since).label('active')
                )
            )
            users = user_stats.first()
            
            # Payment stats
            payment_stats = await session.execute(
                select(
                    func.count(Payment.id).label('count'),
                    func.sum(Payment.amount).label('total_amount')
                ).where(
                    and_(
                        Payment.created_at >= since,
                        Payment.status == PaymentStatus.COMPLETED
                    )
                )
            )
            payments = payment_stats.first()
            
            return {
                'downloads': {
                    'total': downloads.total,
                    'completed': downloads.completed,
                    'failed': downloads.failed,
                    'success_rate': (downloads.completed / downloads.total * 100) if downloads.total > 0 else 0
                },
                'users': {
                    'total': users.total,
                    'new': users.new,
                    'active': users.active
                },
                'payments': {
                    'count': payments.count or 0,
                    'total_amount': float(payments.total_amount or 0)
                }
            }


# Create global database manager instance
db_manager = DatabaseManager()