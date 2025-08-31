"""
Main bot file
"""
import asyncio
import logging
import signal
import sys
from pyrogram import Client, idle
from pyrogram.errors import ApiIdInvalid, AccessTokenInvalid

from config import settings
from database.manager import db_manager
from utils.cache import cache_manager
from services.downloader import download_service
from services.uploader import upload_service
from services.payment import payment_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Disable noisy loggers
logging.getLogger('pyrogram').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)


class YTDLBot:
    """Main bot class"""
    
    def __init__(self):
        self.client = None
        self.running = False
        
    async def initialize(self):
        """Initialize bot and services"""
        logger.info("Initializing bot...")
        
        # Initialize database
        await db_manager.initialize()
        logger.info("Database initialized")
        
        # Initialize cache
        await cache_manager.initialize()
        logger.info("Cache initialized")
        
        # Initialize Pyrogram client
        self.client = Client(
            "ytdl_bot",
            api_id=settings.api_id,
            api_hash=settings.api_hash,
            bot_token=settings.bot_token,
            workers=settings.pyrogram_workers,
            sleep_threshold=60
        )
        
        # Initialize services
        await download_service.initialize()
        await upload_service.initialize(self.client)
        await payment_service.initialize(self.client)
        
        logger.info("All services initialized")
    
    async def start(self):
        """Start the bot"""
        try:
            # Start client
            await self.client.start()
            
            # Get bot info
            me = await self.client.get_me()
            logger.info(f"Bot started as @{me.username} ({me.id})")
            
            # Import handlers
            from handlers import start, download, admin
            
            # Set running flag
            self.running = True
            
            # Start webhook or polling
            if settings.bot_mode == 'webhook':
                await self.start_webhook()
            else:
                logger.info("Bot is running in polling mode...")
                await idle()
            
        except (ApiIdInvalid, AccessTokenInvalid):
            logger.error("Invalid API credentials. Please check your .env file")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            sys.exit(1)
    
    async def start_webhook(self):
        """Start webhook mode"""
        if not settings.webhook_url:
            logger.error("Webhook URL not configured")
            return
        
        # Set webhook
        await self.client.set_webhook(
            url=f"{settings.webhook_url}/webhook",
            max_connections=100,
            drop_pending_updates=True
        )
        
        logger.info(f"Webhook set to {settings.webhook_url}")
        
        # Keep the bot running
        await idle()
    
    async def stop(self):
        """Stop the bot"""
        logger.info("Stopping bot...")
        self.running = False
        
        # Stop services
        await download_service.stop()
        await upload_service.stop()
        
        # Close connections
        await cache_manager.close()
        await db_manager.close()
        
        # Stop client
        if self.client:
            await self.client.stop()
        
        logger.info("Bot stopped")
    
    def handle_signal(self, signum, frame):
        """Handle system signals"""
        logger.info(f"Received signal {signum}")
        asyncio.create_task(self.stop())


async def main():
    """Main function"""
    bot = YTDLBot()
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, bot.handle_signal)
    signal.signal(signal.SIGTERM, bot.handle_signal)
    
    try:
        # Initialize bot
        await bot.initialize()
        
        # Start bot
        await bot.start()
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}", exc_info=True)
    finally:
        await bot.stop()


if __name__ == "__main__":
    # Run the bot
    asyncio.run(main())