"""
Redis cache manager for the bot
"""
import json
import pickle
from typing import Any, Optional, Union, List, Dict
import redis.asyncio as redis
from redis.asyncio.lock import Lock
import logging

from config import settings

logger = logging.getLogger(__name__)


class CacheManager:
    """Redis cache manager"""
    
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self._connected = False
        
    async def initialize(self):
        """Initialize Redis connection"""
        try:
            self.redis = redis.from_url(
                settings.redis_url,
                encoding='utf-8',
                decode_responses=False,
                max_connections=50,
                health_check_interval=30
            )
            
            # Test connection
            await self.redis.ping()
            self._connected = True
            logger.info("Redis cache initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Redis: {e}")
            self._connected = False
    
    async def close(self):
        """Close Redis connection"""
        if self.redis:
            await self.redis.close()
            self._connected = False
            logger.info("Redis connection closed")
    
    def _serialize(self, value: Any) -> bytes:
        """Serialize value for storage"""
        if isinstance(value, (str, int, float, bool)):
            return json.dumps(value).encode('utf-8')
        else:
            return pickle.dumps(value)
    
    def _deserialize(self, data: bytes) -> Any:
        """Deserialize value from storage"""
        if not data:
            return None
        try:
            # Try JSON first
            return json.loads(data.decode('utf-8'))
        except:
            # Fall back to pickle
            return pickle.loads(data)
    
    async def get(self, key: str) -> Any:
        """Get value from cache"""
        if not self._connected:
            return None
            
        try:
            data = await self.redis.get(key)
            return self._deserialize(data) if data else None
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None
    
    async def set(self, key: str, value: Any, expire: Optional[int] = None) -> bool:
        """Set value in cache"""
        if not self._connected:
            return False
            
        try:
            data = self._serialize(value)
            if expire:
                return await self.redis.setex(key, expire, data)
            else:
                return await self.redis.set(key, data)
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache"""
        if not self._connected:
            return False
            
        try:
            return await self.redis.delete(key) > 0
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        if not self._connected:
            return False
            
        try:
            return await self.redis.exists(key) > 0
        except Exception as e:
            logger.error(f"Cache exists error: {e}")
            return False
    
    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration time for key"""
        if not self._connected:
            return False
            
        try:
            return await self.redis.expire(key, seconds)
        except Exception as e:
            logger.error(f"Cache expire error: {e}")
            return False
    
    async def ttl(self, key: str) -> int:
        """Get TTL for key"""
        if not self._connected:
            return -1
            
        try:
            return await self.redis.ttl(key)
        except Exception as e:
            logger.error(f"Cache ttl error: {e}")
            return -1
    
    # Hash operations
    async def hget(self, name: str, key: str) -> Any:
        """Get hash field value"""
        if not self._connected:
            return None
            
        try:
            data = await self.redis.hget(name, key)
            return self._deserialize(data) if data else None
        except Exception as e:
            logger.error(f"Cache hget error: {e}")
            return None
    
    async def hset(self, name: str, key: str, value: Any) -> bool:
        """Set hash field value"""
        if not self._connected:
            return False
            
        try:
            data = self._serialize(value)
            return await self.redis.hset(name, key, data) >= 0
        except Exception as e:
            logger.error(f"Cache hset error: {e}")
            return False
    
    async def hgetall(self, name: str) -> Dict[str, Any]:
        """Get all hash fields"""
        if not self._connected:
            return {}
            
        try:
            data = await self.redis.hgetall(name)
            return {
                k.decode('utf-8'): self._deserialize(v) 
                for k, v in data.items()
            }
        except Exception as e:
            logger.error(f"Cache hgetall error: {e}")
            return {}
    
    async def hdel(self, name: str, *keys: str) -> int:
        """Delete hash fields"""
        if not self._connected:
            return 0
            
        try:
            return await self.redis.hdel(name, *keys)
        except Exception as e:
            logger.error(f"Cache hdel error: {e}")
            return 0
    
    # List operations
    async def lpush(self, key: str, *values: Any) -> int:
        """Push values to list head"""
        if not self._connected:
            return 0
            
        try:
            serialized = [self._serialize(v) for v in values]
            return await self.redis.lpush(key, *serialized)
        except Exception as e:
            logger.error(f"Cache lpush error: {e}")
            return 0
    
    async def rpush(self, key: str, *values: Any) -> int:
        """Push values to list tail"""
        if not self._connected:
            return 0
            
        try:
            serialized = [self._serialize(v) for v in values]
            return await self.redis.rpush(key, *serialized)
        except Exception as e:
            logger.error(f"Cache rpush error: {e}")
            return 0
    
    async def lpop(self, key: str) -> Any:
        """Pop value from list head"""
        if not self._connected:
            return None
            
        try:
            data = await self.redis.lpop(key)
            return self._deserialize(data) if data else None
        except Exception as e:
            logger.error(f"Cache lpop error: {e}")
            return None
    
    async def lrange(self, key: str, start: int, stop: int) -> List[Any]:
        """Get list range"""
        if not self._connected:
            return []
            
        try:
            data = await self.redis.lrange(key, start, stop)
            return [self._deserialize(item) for item in data]
        except Exception as e:
            logger.error(f"Cache lrange error: {e}")
            return []
    
    async def llen(self, key: str) -> int:
        """Get list length"""
        if not self._connected:
            return 0
            
        try:
            return await self.redis.llen(key)
        except Exception as e:
            logger.error(f"Cache llen error: {e}")
            return 0
    
    # Set operations
    async def sadd(self, key: str, *members: Any) -> int:
        """Add members to set"""
        if not self._connected:
            return 0
            
        try:
            serialized = [self._serialize(m) for m in members]
            return await self.redis.sadd(key, *serialized)
        except Exception as e:
            logger.error(f"Cache sadd error: {e}")
            return 0
    
    async def srem(self, key: str, *members: Any) -> int:
        """Remove members from set"""
        if not self._connected:
            return 0
            
        try:
            serialized = [self._serialize(m) for m in members]
            return await self.redis.srem(key, *serialized)
        except Exception as e:
            logger.error(f"Cache srem error: {e}")
            return 0
    
    async def sismember(self, key: str, member: Any) -> bool:
        """Check if member exists in set"""
        if not self._connected:
            return False
            
        try:
            data = self._serialize(member)
            return await self.redis.sismember(key, data)
        except Exception as e:
            logger.error(f"Cache sismember error: {e}")
            return False
    
    async def smembers(self, key: str) -> List[Any]:
        """Get all set members"""
        if not self._connected:
            return []
            
        try:
            data = await self.redis.smembers(key)
            return [self._deserialize(item) for item in data]
        except Exception as e:
            logger.error(f"Cache smembers error: {e}")
            return []
    
    # Counter operations
    async def incr(self, key: str, amount: int = 1) -> int:
        """Increment counter"""
        if not self._connected:
            return 0
            
        try:
            return await self.redis.incrby(key, amount)
        except Exception as e:
            logger.error(f"Cache incr error: {e}")
            return 0
    
    async def decr(self, key: str, amount: int = 1) -> int:
        """Decrement counter"""
        if not self._connected:
            return 0
            
        try:
            return await self.redis.decrby(key, amount)
        except Exception as e:
            logger.error(f"Cache decr error: {e}")
            return 0
    
    # Lock operations
    async def acquire_lock(self, key: str, timeout: int = 10) -> Optional[Lock]:
        """Acquire distributed lock"""
        if not self._connected:
            return None
            
        try:
            lock = self.redis.lock(f"lock:{key}", timeout=timeout)
            if await lock.acquire(blocking=False):
                return lock
            return None
        except Exception as e:
            logger.error(f"Cache lock error: {e}")
            return None
    
    async def release_lock(self, lock: Lock) -> bool:
        """Release distributed lock"""
        try:
            await lock.release()
            return True
        except Exception as e:
            logger.error(f"Cache unlock error: {e}")
            return False
    
    # Cache key helpers
    @staticmethod
    def user_key(user_id: int) -> str:
        """Get user cache key"""
        return f"user:{user_id}"
    
    @staticmethod
    def download_key(download_id: int) -> str:
        """Get download cache key"""
        return f"download:{download_id}"
    
    @staticmethod
    def queue_key(priority: int = 1) -> str:
        """Get download queue key"""
        return f"queue:priority:{priority}"
    
    @staticmethod
    def rate_limit_key(user_id: int, period: str) -> str:
        """Get rate limit key"""
        return f"rate_limit:{user_id}:{period}"
    
    @staticmethod
    def channel_members_key(channel_id: int) -> str:
        """Get channel members key"""
        return f"channel:{channel_id}:members"
    
    @staticmethod
    def analytics_key(event_type: str, date: str) -> str:
        """Get analytics key"""
        return f"analytics:{event_type}:{date}"


# Create global cache manager instance
cache_manager = CacheManager()