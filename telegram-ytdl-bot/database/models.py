"""
Database models for the bot
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean, Float,
    ForeignKey, Text, JSON, BigInteger, Enum, Index,
    UniqueConstraint, CheckConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, backref
from sqlalchemy.sql import func
import enum

Base = declarative_base()


class UserStatus(enum.Enum):
    """User status enumeration"""
    ACTIVE = "active"
    BANNED = "banned"
    RESTRICTED = "restricted"
    PREMIUM = "premium"


class DownloadStatus(enum.Enum):
    """Download status enumeration"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PaymentStatus(enum.Enum):
    """Payment status enumeration"""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class User(Base):
    """User model"""
    __tablename__ = 'users'
    
    id = Column(BigInteger, primary_key=True)
    username = Column(String(32), nullable=True, index=True)
    first_name = Column(String(64), nullable=True)
    last_name = Column(String(64), nullable=True)
    language_code = Column(String(10), default='en')
    
    # Status and permissions
    status = Column(Enum(UserStatus), default=UserStatus.ACTIVE)
    is_admin = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=func.now())
    last_active = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Plan and credits
    plan = Column(String(20), default='free')
    credits = Column(Integer, default=0)
    daily_downloads = Column(Integer, default=0)
    last_download_reset = Column(DateTime, default=func.now())
    
    # Referral system
    referrer_id = Column(BigInteger, ForeignKey('users.id'), nullable=True)
    referral_code = Column(String(16), unique=True, nullable=True)
    referral_earnings = Column(Integer, default=0)
    
    # Settings
    settings = Column(JSON, default={})
    
    # Relationships
    downloads = relationship('Download', back_populates='user', cascade='all, delete-orphan')
    payments = relationship('Payment', back_populates='user', cascade='all, delete-orphan')
    referrals = relationship('User', backref=backref('referrer', remote_side=[id]))
    
    __table_args__ = (
        Index('idx_user_status', 'status'),
        Index('idx_user_plan', 'plan'),
        Index('idx_user_referral', 'referral_code'),
    )
    
    def __repr__(self):
        return f"<User(id={self.id}, username={self.username})>"


class Download(Base):
    """Download model"""
    __tablename__ = 'downloads'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    url = Column(Text, nullable=False)
    title = Column(String(255), nullable=True)
    
    # Status tracking
    status = Column(Enum(DownloadStatus), default=DownloadStatus.PENDING)
    progress = Column(Float, default=0.0)
    
    # File information
    file_size = Column(BigInteger, nullable=True)
    duration = Column(Integer, nullable=True)
    format = Column(String(50), nullable=True)
    quality = Column(String(20), nullable=True)
    
    # Telegram message info
    message_id = Column(Integer, nullable=True)
    file_id = Column(String(255), nullable=True)
    
    # Timing
    created_at = Column(DateTime, default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Error tracking
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    
    # Additional metadata
    extra_metadata = Column(JSON, default={})
    
    # Relationships
    user = relationship('User', back_populates='downloads')
    
    __table_args__ = (
        Index('idx_download_user', 'user_id'),
        Index('idx_download_status', 'status'),
        Index('idx_download_created', 'created_at'),
    )
    
    def __repr__(self):
        return f"<Download(id={self.id}, user_id={self.user_id}, status={self.status})>"


class Payment(Base):
    """Payment model"""
    __tablename__ = 'payments'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    
    # Payment details
    amount = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False)
    credits = Column(Integer, nullable=False)
    plan = Column(String(20), nullable=True)
    
    # Transaction info
    transaction_id = Column(String(255), unique=True, nullable=True)
    provider = Column(String(50), nullable=True)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING)
    
    # Timing
    created_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime, nullable=True)
    
    # Additional data
    extra_metadata = Column(JSON, default={})
    
    # Relationships
    user = relationship('User', back_populates='payments')
    
    __table_args__ = (
        Index('idx_payment_user', 'user_id'),
        Index('idx_payment_status', 'status'),
        Index('idx_payment_transaction', 'transaction_id'),
    )
    
    def __repr__(self):
        return f"<Payment(id={self.id}, user_id={self.user_id}, amount={self.amount})>"


class Channel(Base):
    """Channel model for subscription requirements"""
    __tablename__ = 'channels'
    
    id = Column(BigInteger, primary_key=True)
    username = Column(String(32), nullable=True, unique=True)
    title = Column(String(255), nullable=True)
    
    # Requirements
    is_required = Column(Boolean, default=True)
    is_affiliate = Column(Boolean, default=False)
    reward_credits = Column(Integer, default=0)
    
    # Stats
    added_at = Column(DateTime, default=func.now())
    last_checked = Column(DateTime, nullable=True)
    member_count = Column(Integer, nullable=True)
    
    # Relationships
    subscriptions = relationship('ChannelSubscription', back_populates='channel', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<Channel(id={self.id}, username={self.username})>"


class ChannelSubscription(Base):
    """Channel subscription tracking"""
    __tablename__ = 'channel_subscriptions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    channel_id = Column(BigInteger, ForeignKey('channels.id'), nullable=False)
    
    # Subscription info
    subscribed_at = Column(DateTime, default=func.now())
    is_active = Column(Boolean, default=True)
    last_checked = Column(DateTime, default=func.now())
    
    # Relationships
    user = relationship('User')
    channel = relationship('Channel', back_populates='subscriptions')
    
    __table_args__ = (
        UniqueConstraint('user_id', 'channel_id', name='unique_user_channel'),
        Index('idx_subscription_user', 'user_id'),
        Index('idx_subscription_channel', 'channel_id'),
    )
    
    def __repr__(self):
        return f"<ChannelSubscription(user_id={self.user_id}, channel_id={self.channel_id})>"


class RateLimit(Base):
    """Rate limiting tracking"""
    __tablename__ = 'rate_limits'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, index=True, nullable=False)
    
    # Counters
    minute_count = Column(Integer, default=0)
    hour_count = Column(Integer, default=0)
    day_count = Column(Integer, default=0)
    
    # Reset times
    minute_reset = Column(DateTime, default=func.now())
    hour_reset = Column(DateTime, default=func.now())
    day_reset = Column(DateTime, default=func.now())
    
    # Last action
    last_action = Column(DateTime, default=func.now())
    
    __table_args__ = (
        UniqueConstraint('user_id', name='unique_user_rate_limit'),
    )
    
    def __repr__(self):
        return f"<RateLimit(user_id={self.user_id})>"


class BroadcastMessage(Base):
    """Broadcast message tracking"""
    __tablename__ = 'broadcast_messages'
    
    id = Column(Integer, primary_key=True)
    
    # Message content
    text = Column(Text, nullable=False)
    media_type = Column(String(20), nullable=True)
    media_file_id = Column(String(255), nullable=True)
    
    # Targeting
    target_users = Column(JSON, default=[])  # List of user IDs or 'all'
    target_plan = Column(String(20), nullable=True)
    
    # Stats
    created_at = Column(DateTime, default=func.now())
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    completed = Column(Boolean, default=False)
    
    # Creator
    created_by = Column(BigInteger, nullable=False)
    
    def __repr__(self):
        return f"<BroadcastMessage(id={self.id}, sent={self.sent_count})>"


class Analytics(Base):
    """Analytics tracking"""
    __tablename__ = 'analytics'
    
    id = Column(Integer, primary_key=True)
    
    # Event info
    event_type = Column(String(50), nullable=False)
    user_id = Column(BigInteger, nullable=True)
    
    # Event data
    data = Column(JSON, default={})
    timestamp = Column(DateTime, default=func.now())
    
    __table_args__ = (
        Index('idx_analytics_event', 'event_type'),
        Index('idx_analytics_user', 'user_id'),
        Index('idx_analytics_timestamp', 'timestamp'),
    )
    
    def __repr__(self):
        return f"<Analytics(id={self.id}, event={self.event_type})>"