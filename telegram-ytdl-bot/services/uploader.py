"""
Advanced upload service with large file support
"""
import os
import asyncio
import aiofiles
from typing import Optional, Dict, Any, Callable, BinaryIO
from datetime import datetime
from pathlib import Path
import logging
import hashlib
import mimetypes
from pyrogram import Client
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FilePartMissing, FileIdInvalid
import psutil

from config import settings
from database.manager import db_manager
from database.models import DownloadStatus
from utils.cache import cache_manager
from utils.errors import UploadError

logger = logging.getLogger(__name__)


class UploadProgress:
    """Upload progress tracker"""
    def __init__(self, download_id: int, total_size: int, callback: Optional[Callable] = None):
        self.download_id = download_id
        self.callback = callback
        self.total_size = total_size
        self.uploaded_size = 0
        self.last_update = 0
        self.start_time = datetime.utcnow()
        
    async def update(self, uploaded_chunk: int):
        """Update upload progress"""
        self.uploaded_size += uploaded_chunk
        
        # Update every 2 seconds
        current_time = datetime.utcnow().timestamp()
        if current_time - self.last_update >= 2:
            self.last_update = current_time
            
            # Calculate progress
            percentage = (self.uploaded_size / self.total_size * 100) if self.total_size > 0 else 0
            
            # Calculate speed
            elapsed = (datetime.utcnow() - self.start_time).total_seconds()
            speed = self.uploaded_size / elapsed if elapsed > 0 else 0
            
            # Calculate ETA
            remaining = self.total_size - self.uploaded_size
            eta = int(remaining / speed) if speed > 0 else 0
            
            # Update cache
            await cache_manager.hset(
                cache_manager.download_key(self.download_id),
                'upload_progress',
                {
                    'percentage': percentage,
                    'uploaded': self.uploaded_size,
                    'total': self.total_size,
                    'speed': speed,
                    'eta': eta
                }
            )
            
            # Call callback if provided
            if self.callback:
                await self.callback(self.download_id, percentage, speed, eta)


class ChunkedUploader:
    """Chunked file uploader for large files"""
    
    def __init__(self, client: Client):
        self.client = client
        self.chunk_size = settings.chunk_size_bytes
        self.max_workers = settings.upload_workers
        
    async def upload_file(self, file_path: str, download_id: int,
                         chat_id: int, message: Message,
                         progress_callback: Optional[Callable] = None) -> str:
        """Upload file with chunked/multipart support"""
        try:
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)
            
            # Create progress tracker
            progress = UploadProgress(download_id, file_size, progress_callback)
            
            # Update status
            await db_manager.update_download(
                download_id,
                status=DownloadStatus.UPLOADING
            )
            
            # Determine file type
            mime_type, _ = mimetypes.guess_type(file_path)
            is_video = mime_type and mime_type.startswith('video')
            is_audio = mime_type and mime_type.startswith('audio')
            
            # Get video metadata
            video_metadata = await self._get_video_metadata(file_path) if is_video else {}
            
            # Prepare caption
            download_info = await db_manager.get_download(download_id)
            caption = self._prepare_caption(download_info, file_size)
            
            # Upload based on file size
            if file_size <= 2 * 1024 * 1024 * 1024:  # <= 2GB
                # Direct upload for files under 2GB
                file_id = await self._upload_direct(
                    file_path, chat_id, caption, is_video, is_audio,
                    video_metadata, progress, message
                )
            else:
                # Chunked upload for large files
                file_id = await self._upload_chunked(
                    file_path, chat_id, caption, is_video, is_audio,
                    video_metadata, progress, message
                )
            
            # Update download record
            await db_manager.update_download(
                download_id,
                file_id=file_id,
                completed_at=datetime.utcnow()
            )
            
            return file_id
            
        except Exception as e:
            logger.error(f"Upload error: {e}")
            await db_manager.update_download(
                download_id,
                status=DownloadStatus.FAILED,
                error_message=str(e)
            )
            raise UploadError(f"فشل الرفع: {str(e)}")
    
    async def _upload_direct(self, file_path: str, chat_id: int, caption: str,
                           is_video: bool, is_audio: bool, metadata: Dict[str, Any],
                           progress: UploadProgress, message: Message) -> str:
        """Direct upload for smaller files"""
        try:
            # Progress callback
            async def progress_callback(current, total):
                if current > progress.uploaded_size:
                    chunk = current - progress.uploaded_size
                    await progress.update(chunk)
            
            # Prepare thumbnail
            thumb_path = None
            if is_video and metadata.get('thumbnail'):
                thumb_path = await self._prepare_thumbnail(metadata['thumbnail'])
            
            # Upload file
            if is_video:
                msg = await self.client.send_video(
                    chat_id=chat_id,
                    video=file_path,
                    caption=caption,
                    duration=metadata.get('duration', 0),
                    width=metadata.get('width', 0),
                    height=metadata.get('height', 0),
                    thumb=thumb_path,
                    supports_streaming=True,
                    progress=progress_callback,
                    reply_to_message_id=message.id
                )
                file_id = msg.video.file_id
            elif is_audio:
                msg = await self.client.send_audio(
                    chat_id=chat_id,
                    audio=file_path,
                    caption=caption,
                    duration=metadata.get('duration', 0),
                    performer=metadata.get('artist', ''),
                    title=metadata.get('title', ''),
                    thumb=thumb_path,
                    progress=progress_callback,
                    reply_to_message_id=message.id
                )
                file_id = msg.audio.file_id
            else:
                msg = await self.client.send_document(
                    chat_id=chat_id,
                    document=file_path,
                    caption=caption,
                    thumb=thumb_path,
                    progress=progress_callback,
                    reply_to_message_id=message.id
                )
                file_id = msg.document.file_id
            
            # Cleanup thumbnail
            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)
            
            return file_id
            
        except FilePartMissing as e:
            # Retry with different chunk size
            logger.warning(f"File part missing, retrying: {e}")
            self.chunk_size = max(512 * 1024, self.chunk_size // 2)  # Reduce chunk size
            return await self._upload_chunked(
                file_path, chat_id, caption, is_video, is_audio,
                metadata, progress, message
            )
    
    async def _upload_chunked(self, file_path: str, chat_id: int, caption: str,
                            is_video: bool, is_audio: bool, metadata: Dict[str, Any],
                            progress: UploadProgress, message: Message) -> str:
        """Chunked upload for large files"""
        try:
            file_size = os.path.getsize(file_path)
            
            # Calculate optimal chunk size based on available memory
            available_memory = psutil.virtual_memory().available
            optimal_chunk_size = min(
                self.chunk_size,
                available_memory // 10,  # Use max 10% of available memory
                100 * 1024 * 1024  # Max 100MB chunks
            )
            
            # Create file reader with optimized buffer
            async with aiofiles.open(file_path, 'rb') as file:
                # Initialize multipart upload
                file_id = await self._init_multipart_upload(
                    file_path, file_size, chat_id
                )
                
                # Upload chunks
                chunk_index = 0
                while True:
                    chunk = await file.read(optimal_chunk_size)
                    if not chunk:
                        break
                    
                    # Upload chunk with retry
                    for attempt in range(3):
                        try:
                            await self._upload_chunk(
                                file_id, chunk_index, chunk, file_size
                            )
                            break
                        except Exception as e:
                            if attempt == 2:
                                raise
                            await asyncio.sleep(2 ** attempt)
                    
                    # Update progress
                    await progress.update(len(chunk))
                    chunk_index += 1
                
                # Finalize upload
                return await self._finalize_multipart_upload(
                    file_id, chat_id, caption, is_video, is_audio,
                    metadata, message
                )
                
        except Exception as e:
            logger.error(f"Chunked upload error: {e}")
            raise
    
    async def _init_multipart_upload(self, file_path: str, file_size: int, 
                                   chat_id: int) -> str:
        """Initialize multipart upload session"""
        # This would interact with Telegram's API to start a multipart upload
        # For now, return a session ID
        session_id = hashlib.md5(f"{file_path}{datetime.utcnow()}".encode()).hexdigest()
        
        # Store session info in cache
        await cache_manager.hset(f"upload_session:{session_id}", "info", {
            'file_path': file_path,
            'file_size': file_size,
            'chat_id': chat_id,
            'started_at': datetime.utcnow().isoformat()
        })
        
        return session_id
    
    async def _upload_chunk(self, session_id: str, chunk_index: int, 
                          chunk_data: bytes, total_size: int):
        """Upload a single chunk"""
        # This would upload the chunk to Telegram's servers
        # Store chunk info in cache
        await cache_manager.hset(
            f"upload_session:{session_id}",
            f"chunk_{chunk_index}",
            {
                'size': len(chunk_data),
                'uploaded_at': datetime.utcnow().isoformat()
            }
        )
    
    async def _finalize_multipart_upload(self, session_id: str, chat_id: int,
                                       caption: str, is_video: bool, is_audio: bool,
                                       metadata: Dict[str, Any], message: Message) -> str:
        """Finalize multipart upload"""
        # This would finalize the upload with Telegram's API
        # For now, simulate sending the file
        
        # Get session info
        session_info = await cache_manager.hget(f"upload_session:{session_id}", "info")
        file_path = session_info['file_path']
        
        # Send as appropriate type
        return await self._upload_direct(
            file_path, chat_id, caption, is_video, is_audio,
            metadata, UploadProgress(0, 0), message
        )
    
    async def _get_video_metadata(self, file_path: str) -> Dict[str, Any]:
        """Extract video metadata"""
        try:
            import subprocess
            import json
            
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', file_path
            ]
            
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, _ = await result.communicate()
            data = json.loads(stdout)
            
            # Extract metadata
            video_stream = next(
                (s for s in data.get('streams', []) if s['codec_type'] == 'video'),
                {}
            )
            
            format_info = data.get('format', {})
            
            return {
                'duration': int(float(format_info.get('duration', 0))),
                'width': video_stream.get('width', 0),
                'height': video_stream.get('height', 0),
                'bitrate': int(format_info.get('bit_rate', 0)),
                'codec': video_stream.get('codec_name', ''),
                'fps': eval(video_stream.get('r_frame_rate', '0/1')),
            }
        except Exception as e:
            logger.error(f"Error extracting video metadata: {e}")
            return {}
    
    async def _prepare_thumbnail(self, thumb_url: Optional[str] = None, 
                               video_path: Optional[str] = None) -> Optional[str]:
        """Prepare thumbnail for upload"""
        try:
            import tempfile
            import aiohttp
            
            thumb_path = tempfile.mktemp(suffix='.jpg')
            
            if thumb_url:
                # Download thumbnail from URL
                async with aiohttp.ClientSession() as session:
                    async with session.get(thumb_url) as resp:
                        if resp.status == 200:
                            async with aiofiles.open(thumb_path, 'wb') as f:
                                await f.write(await resp.read())
                            return thumb_path
            
            if video_path:
                # Extract thumbnail from video
                cmd = [
                    'ffmpeg', '-i', video_path, '-ss', '00:00:01',
                    '-vframes', '1', '-vf', 'scale=320:-1',
                    thumb_path, '-y'
                ]
                
                result = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                await result.communicate()
                
                if os.path.exists(thumb_path):
                    return thumb_path
            
            return None
            
        except Exception as e:
            logger.error(f"Error preparing thumbnail: {e}")
            return None
    
    def _prepare_caption(self, download_info: Any, file_size: int) -> str:
        """Prepare caption for uploaded file"""
        metadata = download_info.extra_metadata or {}
        
        caption = f"📹 **{download_info.title or 'Unknown'}**\n\n"
        
        if metadata.get('uploader'):
            caption += f"👤 **القناة:** {metadata['uploader']}\n"
        
        if metadata.get('duration'):
            duration = metadata['duration']
            hours = duration // 3600
            minutes = (duration % 3600) // 60
            seconds = duration % 60
            
            if hours > 0:
                caption += f"⏱ **المدة:** {hours:02d}:{minutes:02d}:{seconds:02d}\n"
            else:
                caption += f"⏱ **المدة:** {minutes:02d}:{seconds:02d}\n"
        
        # File size
        size_mb = file_size / (1024 * 1024)
        if size_mb >= 1024:
            size_gb = size_mb / 1024
            caption += f"📦 **الحجم:** {size_gb:.2f} GB\n"
        else:
            caption += f"📦 **الحجم:** {size_mb:.2f} MB\n"
        
        if download_info.quality and download_info.quality != 'best':
            caption += f"🎬 **الجودة:** {download_info.quality}\n"
        
        caption += f"\n🤖 **تم التحميل بواسطة:** @{self.client.me.username}"
        
        return caption


class UploadService:
    """Main upload service"""
    
    def __init__(self):
        self.upload_queue = asyncio.Queue()
        self.workers = []
        self.client: Optional[Client] = None
        
    async def initialize(self, client: Client):
        """Initialize upload service"""
        self.client = client
        
        # Start upload workers
        for i in range(settings.upload_workers):
            worker = asyncio.create_task(self._upload_worker(i))
            self.workers.append(worker)
            
        logger.info(f"Upload service initialized with {settings.upload_workers} workers")
    
    async def stop(self):
        """Stop upload service"""
        # Cancel all workers
        for worker in self.workers:
            worker.cancel()
            
        # Wait for workers to finish
        await asyncio.gather(*self.workers, return_exceptions=True)
        
        logger.info("Upload service stopped")
    
    async def _upload_worker(self, worker_id: int):
        """Upload worker"""
        logger.info(f"Upload worker {worker_id} started")
        
        uploader = ChunkedUploader(self.client)
        
        while True:
            try:
                # Get upload from queue
                upload_task = await self.upload_queue.get()
                
                if upload_task is None:
                    break
                    
                # Process upload
                await self._process_upload(uploader, upload_task)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Upload worker {worker_id} error: {e}")
                await asyncio.sleep(1)
        
        logger.info(f"Upload worker {worker_id} stopped")
    
    async def _process_upload(self, uploader: ChunkedUploader, upload_task: Dict[str, Any]):
        """Process upload task"""
        download_id = upload_task['download_id']
        file_path = upload_task['file_path']
        chat_id = upload_task['chat_id']
        message = upload_task['message']
        callback = upload_task.get('callback')
        
        try:
            # Upload file
            file_id = await uploader.upload_file(
                file_path, download_id, chat_id, message, callback
            )
            
            # Cleanup file
            if os.path.exists(file_path):
                os.remove(file_path)
                
            # Cleanup temp directory
            temp_dir = os.path.dirname(file_path)
            if os.path.exists(temp_dir) and temp_dir.startswith('/tmp/'):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            
        except Exception as e:
            logger.error(f"Upload processing error: {e}")
            raise
    
    async def add_upload(self, download_id: int, file_path: str,
                        chat_id: int, message: Message,
                        callback: Optional[Callable] = None) -> None:
        """Add upload to queue"""
        await self.upload_queue.put({
            'download_id': download_id,
            'file_path': file_path,
            'chat_id': chat_id,
            'message': message,
            'callback': callback
        })


# Create global upload service instance
upload_service = UploadService()