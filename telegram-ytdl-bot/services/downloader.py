"""
Advanced video downloader service using yt-dlp and aria2
"""
import os
import asyncio
import tempfile
import shutil
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime
import yt_dlp
import aria2p
from pathlib import Path
import logging

from config import settings, PLANS
from database.manager import db_manager
from database.models import DownloadStatus
from utils.cache import cache_manager
from utils.errors import DownloadError

logger = logging.getLogger(__name__)


class DownloadProgress:
    """Download progress tracker"""
    def __init__(self, download_id: int, callback: Optional[Callable] = None):
        self.download_id = download_id
        self.callback = callback
        self.last_update = 0
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self.speed = 0
        self.eta = 0
        
    async def update(self, downloaded: int, total: int, speed: float, eta: int):
        """Update progress"""
        self.downloaded_bytes = downloaded
        self.total_bytes = total
        self.speed = speed
        self.eta = eta
        
        # Update every 2 seconds
        current_time = datetime.utcnow().timestamp()
        if current_time - self.last_update >= 2:
            self.last_update = current_time
            
            # Calculate percentage
            percentage = (downloaded / total * 100) if total > 0 else 0
            
            # Update database
            await db_manager.update_download(
                self.download_id,
                progress=percentage
            )
            
            # Update cache
            await cache_manager.hset(
                cache_manager.download_key(self.download_id),
                'progress',
                {
                    'percentage': percentage,
                    'downloaded': downloaded,
                    'total': total,
                    'speed': speed,
                    'eta': eta
                }
            )
            
            # Call callback if provided
            if self.callback:
                await self.callback(self.download_id, percentage, speed, eta)


class YtDlpDownloader:
    """YouTube-DL downloader"""
    
    def __init__(self):
        self.downloads = {}
        
    def _get_ydl_opts(self, output_path: str, quality: str = 'best', 
                      progress_hook: Optional[Callable] = None) -> Dict[str, Any]:
        """Get yt-dlp options"""
        opts = {
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'no_color': True,
            'concurrent_fragment_downloads': 5,
            'buffersize': 1024 * 1024,  # 1MB buffer
            'http_chunk_size': 1024 * 1024,  # 1MB chunks
            'retries': 3,
            'fragment_retries': 3,
            'skip_unavailable_fragments': True,
            'keepvideo': False,
            'overwrites': True,
            'continuedl': True,
            'noprogress': False,
            'ratelimit': None,  # No rate limit
            'throttledratelimit': None,
            'cookiesfrombrowser': None,
            'nocheckcertificate': True,
            'prefer_insecure': True,
            'geo_bypass': True,
            'socket_timeout': 30,
            'source_address': '0.0.0.0',
        }
        
        # Set format based on quality
        if quality == 'audio':
            opts['format'] = 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }]
        else:
            if quality == 'best':
                opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            else:
                # Try to get specific quality
                height = quality.rstrip('p')
                opts['format'] = f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}][ext=mp4]/best[ext=mp4]/best'
        
        # Add progress hook
        if progress_hook:
            opts['progress_hooks'] = [progress_hook]
            
        # Enable aria2c as external downloader for better performance
        if settings.aria2_rpc_url:
            opts['external_downloader'] = 'aria2c'
            opts['external_downloader_args'] = [
                '--continue=true',
                '--max-connection-per-server=16',
                '--split=16',
                '--min-split-size=1M',
                '--max-tries=5',
                '--retry-wait=5',
                '--timeout=60',
                '--allow-overwrite=true',
                '--auto-file-renaming=false',
                f'--rpc-secret={settings.aria2_secret}' if settings.aria2_secret else '',
                '--check-certificate=false',
                '--console-log-level=error'
            ]
        
        return opts
    
    async def get_info(self, url: str) -> Dict[str, Any]:
        """Get video information"""
        try:
            loop = asyncio.get_event_loop()
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'skip_download': True,
                'no_color': True,
                'geo_bypass': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, ydl.extract_info, url, False)
                
            if not info:
                raise DownloadError("لا يمكن الحصول على معلومات الفيديو")
                
            # Extract relevant information
            return {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count', 0),
                'like_count': info.get('like_count', 0),
                'upload_date': info.get('upload_date', ''),
                'description': info.get('description', '')[:500],
                'thumbnail': info.get('thumbnail', ''),
                'formats': self._extract_formats(info.get('formats', [])),
                'is_live': info.get('is_live', False),
                'is_playlist': 'playlist' in url or info.get('_type') == 'playlist',
                'playlist_count': info.get('playlist_count', 0),
                'extractor': info.get('extractor', ''),
                'webpage_url': info.get('webpage_url', url),
                'video_id': info.get('id', ''),
            }
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            raise DownloadError(f"خطأ في الحصول على معلومات الفيديو: {str(e)}")
    
    def _extract_formats(self, formats: List[Dict]) -> List[Dict[str, Any]]:
        """Extract available formats"""
        extracted = []
        seen = set()
        
        for fmt in formats:
            if not fmt.get('url'):
                continue
                
            height = fmt.get('height', 0)
            if height == 0:
                continue
                
            quality = f"{height}p"
            if quality in seen:
                continue
                
            seen.add(quality)
            
            extracted.append({
                'quality': quality,
                'format_id': fmt.get('format_id', ''),
                'ext': fmt.get('ext', 'mp4'),
                'filesize': fmt.get('filesize', 0),
                'vcodec': fmt.get('vcodec', 'unknown'),
                'acodec': fmt.get('acodec', 'unknown'),
                'fps': fmt.get('fps', 0),
                'resolution': fmt.get('resolution', f"{fmt.get('width', 0)}x{height}"),
            })
        
        # Sort by quality
        extracted.sort(key=lambda x: int(x['quality'].rstrip('p')), reverse=True)
        
        return extracted
    
    async def download(self, url: str, download_id: int, 
                      quality: str = 'best',
                      progress_callback: Optional[Callable] = None) -> str:
        """Download video"""
        try:
            # Create temporary directory
            temp_dir = tempfile.mkdtemp(prefix=f'ytdl_{download_id}_')
            output_path = os.path.join(temp_dir, '%(title).200s.%(ext)s')
            
            # Create progress tracker
            progress = DownloadProgress(download_id, progress_callback)
            
            def progress_hook(d):
                """Progress hook for yt-dlp"""
                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded = d.get('downloaded_bytes', 0)
                    speed = d.get('speed', 0) or 0
                    eta = d.get('eta', 0) or 0
                    
                    # Run async update in sync context
                    asyncio.create_task(
                        progress.update(downloaded, total, speed, eta)
                    )
                elif d['status'] == 'finished':
                    asyncio.create_task(
                        progress.update(
                            d.get('total_bytes', 0),
                            d.get('total_bytes', 0),
                            0, 0
                        )
                    )
            
            # Get download options
            ydl_opts = self._get_ydl_opts(output_path, quality, progress_hook)
            
            # Update download status
            await db_manager.update_download(
                download_id,
                status=DownloadStatus.DOWNLOADING,
                started_at=datetime.utcnow()
            )
            
            # Start download
            loop = asyncio.get_event_loop()
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                await loop.run_in_executor(None, ydl.download, [url])
            
            # Find downloaded file
            files = list(Path(temp_dir).glob('*'))
            if not files:
                raise DownloadError("لم يتم تحميل أي ملف")
            
            # Get the largest file (in case of multiple files)
            downloaded_file = max(files, key=lambda f: f.stat().st_size)
            
            # Update download info
            file_size = downloaded_file.stat().st_size
            await db_manager.update_download(
                download_id,
                status=DownloadStatus.PROCESSING,
                file_size=file_size,
                format=downloaded_file.suffix.lstrip('.')
            )
            
            return str(downloaded_file)
            
        except Exception as e:
            logger.error(f"Download error for {url}: {e}")
            await db_manager.update_download(
                download_id,
                status=DownloadStatus.FAILED,
                error_message=str(e)
            )
            raise DownloadError(f"فشل التحميل: {str(e)}")
    
    def cleanup_download(self, file_path: str):
        """Cleanup downloaded files"""
        try:
            # Remove the file
            if os.path.exists(file_path):
                os.remove(file_path)
                
            # Remove the directory
            temp_dir = os.path.dirname(file_path)
            if os.path.exists(temp_dir) and temp_dir.startswith('/tmp/ytdl_'):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            logger.error(f"Error cleaning up download: {e}")


class Aria2Downloader:
    """Aria2 downloader for direct downloads"""
    
    def __init__(self):
        self.aria2: Optional[aria2p.API] = None
        self._connected = False
        
    async def initialize(self):
        """Initialize Aria2 connection"""
        try:
            # Parse RPC URL
            parsed = urllib.parse.urlparse(settings.aria2_rpc_url)
            
            self.aria2 = aria2p.API(
                aria2p.Client(
                    host=parsed.hostname or 'localhost',
                    port=parsed.port or 6800,
                    secret=settings.aria2_secret
                )
            )
            
            # Test connection
            version = self.aria2.get_version()
            self._connected = True
            logger.info(f"Aria2 initialized: v{version['version']}")
        except Exception as e:
            logger.error(f"Failed to initialize Aria2: {e}")
            self._connected = False
    
    async def download_direct(self, url: str, download_id: int,
                            output_dir: str,
                            progress_callback: Optional[Callable] = None) -> str:
        """Download file directly using Aria2"""
        if not self._connected:
            raise DownloadError("Aria2 غير متصل")
            
        try:
            # Add download
            options = {
                'dir': output_dir,
                'continue': 'true',
                'max-connection-per-server': 16,
                'split': 16,
                'min-split-size': '1M',
                'max-tries': 5,
                'retry-wait': 5,
                'timeout': 60,
                'check-certificate': 'false',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            
            download = self.aria2.add_uris([url], options=options)
            
            # Monitor progress
            while not download.is_complete:
                download.update()
                
                if download.has_failed:
                    raise DownloadError(f"فشل التحميل: {download.error_message}")
                
                # Update progress
                if progress_callback and download.total_length > 0:
                    percentage = (download.completed_length / download.total_length) * 100
                    await progress_callback(
                        download_id,
                        percentage,
                        download.download_speed,
                        download.eta
                    )
                
                await asyncio.sleep(1)
            
            # Get downloaded file path
            if download.files:
                return download.files[0].path
            else:
                raise DownloadError("لم يتم تحميل أي ملف")
                
        except Exception as e:
            logger.error(f"Aria2 download error: {e}")
            raise DownloadError(f"خطأ في التحميل: {str(e)}")


class DownloadService:
    """Main download service"""
    
    def __init__(self):
        self.ytdl = YtDlpDownloader()
        self.aria2 = Aria2Downloader()
        self.active_downloads = {}
        self.download_queue = asyncio.Queue()
        self.workers = []
        
    async def initialize(self):
        """Initialize download service"""
        await self.aria2.initialize()
        
        # Start download workers
        for i in range(settings.download_workers):
            worker = asyncio.create_task(self._download_worker(i))
            self.workers.append(worker)
            
        logger.info(f"Download service initialized with {settings.download_workers} workers")
    
    async def stop(self):
        """Stop download service"""
        # Cancel all workers
        for worker in self.workers:
            worker.cancel()
            
        # Wait for workers to finish
        await asyncio.gather(*self.workers, return_exceptions=True)
        
        logger.info("Download service stopped")
    
    async def _download_worker(self, worker_id: int):
        """Download worker"""
        logger.info(f"Download worker {worker_id} started")
        
        while True:
            try:
                # Get download from queue
                download_task = await self.download_queue.get()
                
                if download_task is None:
                    break
                    
                # Process download
                await self._process_download(download_task)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Download worker {worker_id} error: {e}")
                await asyncio.sleep(1)
        
        logger.info(f"Download worker {worker_id} stopped")
    
    async def _process_download(self, download_task: Dict[str, Any]):
        """Process download task"""
        download_id = download_task['download_id']
        url = download_task['url']
        quality = download_task.get('quality', 'best')
        callback = download_task.get('callback')
        
        try:
            # Download video
            file_path = await self.ytdl.download(
                url, download_id, quality, callback
            )
            
            # Update download status
            await db_manager.update_download(
                download_id,
                status=DownloadStatus.COMPLETED,
                completed_at=datetime.utcnow()
            )
            
            # Store in active downloads
            self.active_downloads[download_id] = {
                'file_path': file_path,
                'completed_at': datetime.utcnow()
            }
            
            # Cleanup old downloads
            await self._cleanup_old_downloads()
            
        except Exception as e:
            logger.error(f"Download processing error: {e}")
            await db_manager.update_download(
                download_id,
                status=DownloadStatus.FAILED,
                error_message=str(e)
            )
    
    async def _cleanup_old_downloads(self):
        """Cleanup old completed downloads"""
        current_time = datetime.utcnow()
        to_remove = []
        
        for download_id, info in self.active_downloads.items():
            # Remove downloads older than 1 hour
            if (current_time - info['completed_at']).total_seconds() > 3600:
                self.ytdl.cleanup_download(info['file_path'])
                to_remove.append(download_id)
        
        for download_id in to_remove:
            del self.active_downloads[download_id]
    
    async def add_download(self, user_id: int, url: str, 
                         quality: str = 'best',
                         callback: Optional[Callable] = None) -> int:
        """Add download to queue"""
        # Check user plan and limits
        user = await db_manager.get_user(user_id)
        if not user:
            raise DownloadError("المستخدم غير موجود")
        
        plan = PLANS.get(user.plan, PLANS['free'])
        
        # Check daily limit
        daily_downloads = await db_manager.get_user_daily_downloads(user_id)
        if plan['daily_downloads'] != -1 and daily_downloads >= plan['daily_downloads']:
            raise DownloadError(f"لقد تجاوزت الحد اليومي للتحميلات ({plan['daily_downloads']} تحميل)")
        
        # Get video info
        info = await self.ytdl.get_info(url)
        
        # Check if it's a live stream
        if info['is_live']:
            raise DownloadError("لا يمكن تحميل البث المباشر")
        
        # Check if it's a playlist
        if info['is_playlist'] and 'playlist_support' not in plan['features']:
            raise DownloadError("خطتك لا تدعم تحميل قوائم التشغيل")
        
        # Create download record
        download = await db_manager.create_download(
            user_id=user_id,
            url=url,
            title=info['title'],
            duration=info['duration'],
            quality=quality,
            extra_metadata=info
        )
        
        # Add to queue based on priority
        await self.download_queue.put({
            'download_id': download.id,
            'url': url,
            'quality': quality,
            'callback': callback,
            'priority': plan['priority']
        })
        
        return download.id
    
    async def get_download_progress(self, download_id: int) -> Optional[Dict[str, Any]]:
        """Get download progress"""
        # Check cache first
        progress = await cache_manager.hget(
            cache_manager.download_key(download_id),
            'progress'
        )
        
        if progress:
            return progress
            
        # Get from database
        download = await db_manager.get_download(download_id)
        if download:
            return {
                'status': download.status.value,
                'progress': download.progress,
                'error': download.error_message
            }
            
        return None
    
    def get_download_file(self, download_id: int) -> Optional[str]:
        """Get downloaded file path"""
        if download_id in self.active_downloads:
            return self.active_downloads[download_id]['file_path']
        return None


# Create global download service instance
download_service = DownloadService()