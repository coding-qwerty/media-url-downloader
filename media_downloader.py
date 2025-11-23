import sys
import os
import subprocess
from pathlib import Path
from PyQt5.QtCore import QEvent
import logging
import json
import re
import requests
from urllib.parse import urlparse
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

# ====== APPLICATION CONSTANTS ======
class Config:
    # Window settings
    WINDOW_WIDTH = 480
    WINDOW_HEIGHT = 600
    
    # Colors
    OLED_BLACK = "#000000"
    OLED_DARK_GRAY = "#181A1B"  
    NEON_GREEN = "#39FF14"
    BRIGHT_YELLOW = "#FFEB3B"
    WHITE = "#FFFFFF"
    LIGHT_GRAY = "#DDDDDD"
    DARK_GRAY = "#222222"
    ERROR_RED = "#8B0000"
    SUCCESS_GREEN = "#006400"
    YOUTUBE_RED = "#FF0000"
    
    # UI sizes
    ICON_SIZE = 32
    GIF_SIZE = 80
    URL_INPUT_HEIGHT = 36
    BUTTON_HEIGHT = 30
    DOWNLOAD_BUTTON_HEIGHT = 40
    PROGRESS_BAR_HEIGHT = 25
    
    # Fonts
    TITLE_FONT_SIZE = 12
    LABEL_FONT_SIZE = 11
    ICON_FONT_SIZE = 20
    
    # Paths (these will be the defaults, can be changed via settings)
    DEFAULT_OUTPUT_DIR = os.path.join(str(Path.home()), "Downloads", "YouTube Videos")
    GIF_PATH = os.path.join(str(Path.home()), "Downloads", "giphy.gif")
    LOG_FILE = "downloader_errors.log"

# Configure logging
logging.basicConfig(filename=Config.LOG_FILE, level=logging.ERROR)

class Platform(Enum):
    YOUTUBE = "YouTube"
    TIKTOK = "TikTok"
    TWITTER = "Twitter"
    IMAGE = "Image"
    UNKNOWN = "Unknown"

@dataclass
class DownloadRecord:
    """Track download history with full attribution using a dataclass."""
    url: str
    platform: str
    creator: str = ""
    title: str = ""
    download_date: str = datetime.now().isoformat()
    file_path: str = ""

    def to_dict(self):
        return {
            'url': self.url,
            'title': self.title,
            'creator': self.creator,
            'platform': self.platform,
            'download_date': self.download_date,
            'file_path': self.file_path
        }


def organize_by_creator(download_path, creator, platform):
    """Organize downloads by platform/creator (hierarchical)."""
    try:
        safe_platform = re.sub(r'[<>:"/\\|?*]', '_', platform) if platform else 'Unknown'
        safe_creator = re.sub(r'[<>:"/\\|?*]', '_', creator) if creator else 'Unknown'
        target = os.path.join(download_path, safe_platform, safe_creator)
        os.makedirs(target, exist_ok=True)
        return target
    except Exception:
        return download_path

# Determine if in portable mode (i.e., run from USB or external drive)
PORTABLE_MODE = False  # Set to True for portable, False for normal

if PORTABLE_MODE:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
    DOWNLOADS_DIR = os.path.join(APP_DIR, "downloads")
else:
    SETTINGS_FILE = os.path.join(str(Path.home()), ".yt_downloader_settings.json")
    DOWNLOADS_DIR = os.path.join(str(Path.home()), "YouTubeDownloads")

# Load settings or use defaults
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        logging.error(f"Failed to save settings: {e}")

# Load current settings
current_settings = load_settings()
OUTPUT_DIR = current_settings.get('output_dir', Config.DEFAULT_OUTPUT_DIR)

# Ensure both directories exist
if not os.path.exists(DOWNLOADS_DIR):
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# This is the critical fix - ensure OUTPUT_DIR exists!
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def download_image(url, progress_callback=None):
    """
    Downloads an image from a direct URL.
    
    Parameters:
        url (str): Direct URL to the image file
        progress_callback (callable, optional): Function to receive progress updates
    
    Returns:
        str: Path to downloaded file
    
    Raises:
        Exception: If download fails
    """
    try:
        # Get the image
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, stream=True)
        response.raise_for_status()
        
        # Try to get filename from URL or Content-Disposition header
        filename = None
        if 'content-disposition' in response.headers:
            cd = response.headers['content-disposition']
            if 'filename=' in cd:
                filename = cd.split('filename=')[1].strip('"')
        
        if not filename:
            # Extract filename from URL
            parsed_url = urlparse(url)
            filename = os.path.basename(parsed_url.path)
            if not filename or '.' not in filename:
                # Generate filename based on content type
                content_type = response.headers.get('content-type', '')
                if 'jpeg' in content_type or 'jpg' in content_type:
                    filename = f"image_{hash(url) % 10000}.jpg"
                elif 'png' in content_type:
                    filename = f"image_{hash(url) % 10000}.png"
                elif 'gif' in content_type:
                    filename = f"image_{hash(url) % 10000}.gif"
                elif 'webp' in content_type:
                    filename = f"image_{hash(url) % 10000}.webp"
                else:
                    filename = f"image_{hash(url) % 10000}.jpg"
        
        # Sanitize filename
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        # Download with progress tracking
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        percent = int((downloaded * 100) / total_size)
                        progress_callback(min(percent, 100))
        
        if progress_callback:
            progress_callback(100)
            
        return filepath
        
    except Exception as e:
        raise Exception(f"Failed to download image: {str(e)}")

def is_image_url(url):
    """Check if URL points to an image file"""
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico']
    parsed_url = urlparse(url.lower())
    path = parsed_url.path
    
    # Check for direct image extensions
    if any(path.endswith(ext) for ext in image_extensions):
        return True
    
    # Check for Twitter image URLs with format parameter
    if 'pbs.twimg.com' in parsed_url.netloc or 'twimg.com' in parsed_url.netloc:
        if 'format=jpg' in url or 'format=png' in url or 'format=webp' in url:
            return True
    
    return False

def is_twitter_media_url(url):
    """Check if URL is a Twitter/X post that might contain media"""
    twitter_domains = ['twitter.com', 'x.com', 'www.twitter.com', 'mobile.twitter.com']
    return any(domain in url.lower() for domain in twitter_domains) and '/status/' in url.lower()

def is_tiktok_url(url):  # Keeping the single instance
    """Check if URL is a TikTok video URL"""
    tiktok_domains = ['tiktok.com', 'www.tiktok.com', 'vm.tiktok.com', 'm.tiktok.com']
    return any(domain in url.lower() for domain in tiktok_domains)

def is_video_url(url):
    """Check if URL is a video platform URL"""
    video_domains = [
        'youtube.com', 'youtu.be', 'www.youtube.com', 'm.youtube.com',
        'tiktok.com', 'www.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'
    ]
    return any(domain in url.lower() for domain in video_domains)

def detect_platform(url: str) -> Platform:
    """Return Platform enum for a given URL string."""
    if not url:
        return Platform.UNKNOWN
    u = url.lower()
    if 'youtube.com' in u or 'youtu.be' in u:
        return Platform.YOUTUBE
    if 'tiktok.com' in u or 'vt.tiktok.com' in u or 'vm.tiktok.com' in u:
        return Platform.TIKTOK
    if 'twitter.com' in u or 'x.com' in u:
        return Platform.TWITTER
    if is_image_url(url):
        return Platform.IMAGE
    return Platform.UNKNOWN

    """Check if URL is a TikTok video URL"""  # Keeping the single instance
    tiktok_domains = ['tiktok.com', 'www.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com']
    return any(domain in url.lower() for domain in tiktok_domains)  # Keeping the single instance

def download_media(url, quality="1080p", progress_callback=None, download_subtitles=False):
    """
    Generic media downloader using yt-dlp with creator attribution.

    Parameters:
        url (str): Media URL (YouTube / TikTok / Twitter).
        quality (str): Desired quality preset.
        progress_callback (callable): Progress updates (0-100).
        download_subtitles (bool): Fetch subtitles (YouTube only).
    Returns:
        DownloadRecord
    Raises:
        Exception when download fails.
    """
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed. Please install it with 'pip install yt-dlp'.")

    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    format_map = {
        "audio": "bestaudio/best",
        "4k": "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
        "2k": "bestvideo[height<=1440]+bestaudio/best[height<=1440]",
        "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
        "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]",
    }
    
    # Determine platform via simple matching
    lowered = url.lower()
    if "youtube.com" in lowered or "youtu.be" in lowered:
        platform = Platform.YOUTUBE.value
    elif "tiktok.com" in lowered:
        platform = Platform.TIKTOK.value
    elif "twitter.com" in lowered or "x.com" in lowered:
        platform = Platform.TWITTER.value
    else:
        platform = Platform.UNKNOWN.value
    
    # For TikTok and Twitter, use best available format as they often have limited options
    is_tiktok = platform == "TikTok"
    is_twitter = platform == "Twitter"
    
    if is_tiktok or is_twitter:
        format_str = "best"
    else:
        format_str = format_map.get(quality, "best")

    error_occurred = {"flag": False, "msg": ""}
    video_info = {"title": None, "uploader": None}

    def ydl_progress_hook(d):
        if d.get('status') == 'error':
            error_occurred["flag"] = True
            error_occurred["msg"] = d.get('error', 'Unknown error')
        if progress_callback and d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            speed = d.get('speed', 0)
            eta = d.get('eta', 0)
            if total:
                percent = int(downloaded * 100 / total)
                progress_callback(percent)
            else:
                progress_callback(0)
            if speed and eta and hasattr(progress_callback, 'update_speed'):
                speed_str = f"{speed/1024/1024:.2f} MB/s"
                eta_str = f"{int(eta//60)}m {int(eta%60)}s"
                progress_callback.update_speed.emit(f"Speed: {speed_str} | ETA: {eta_str}")
        elif progress_callback and d.get('status') == 'finished':
            progress_callback(100)
            if hasattr(progress_callback, 'update_speed'):
                progress_callback.update_speed.emit("")

    # Create organized output directory based on platform and creator
    temp_output_dir = OUTPUT_DIR  # We'll update this after getting video info
    
    ydl_opts = {
        'outtmpl': os.path.join(temp_output_dir, '%(uploader)s - %(title).150s.%(ext)s'),
        'format': format_str,
        'progress_hooks': [ydl_progress_hook],
        'noplaylist': True,
        'quiet': True,
        'merge_output_format': 'mp4',
        'http_headers': {
            'User-Agent': user_agent
        },
        'concurrent_fragment_downloads': 5,
        'restrictfilenames': True,
        'windowsfilenames': True,
    }
    
    # Add subtitle options if requested (mainly for YouTube, limited for TikTok/Twitter)
    if download_subtitles and not (is_tiktok or is_twitter):
        ydl_opts.update({
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en', 'en-US'],
            'subtitlesformat': 'srt',
        })
    
    # Ensure output directory exists
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Test write permissions
    try:
        test_file = os.path.join(OUTPUT_DIR, "test_write.tmp")
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
    except Exception as e:
        raise Exception(f"Cannot write to output directory '{OUTPUT_DIR}': {str(e)}")
    
    try:
        # First, extract video info without downloading
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            video_info["title"] = info.get('title', 'Unknown Title')
            video_info["uploader"] = info.get('uploader', 'Unknown Creator')
        
        # Create organized folder based on creator and platform
        organized_dir = organize_by_creator(OUTPUT_DIR, video_info["uploader"], platform)
        ydl_opts['outtmpl'] = os.path.join(organized_dir, '%(uploader)s - %(title).150s.%(ext)s')
        
        # Now download with organized path
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        if error_occurred["flag"]:
            raise Exception(f"yt-dlp error: {error_occurred['msg']}")
        
        # Create download record for attribution tracking
        record = DownloadRecord(
            url=url,
            platform=platform,
            creator=video_info["uploader"],
            title=video_info["title"],
            file_path=organized_dir
        )
        
        # Save to download history
        save_download_history(record)
        
        return record
        
    except Exception as e:
        # More specific error messages
        error_msg = str(e)
        if "No such file or directory" in error_msg:
            raise Exception("Download failed due to filename/path issues. Please try a different download folder or check permissions.")
        elif "nsig extraction failed" in error_msg:
            raise Exception("YouTube has updated their security. Please update yt-dlp: pip install --upgrade yt-dlp")
        else:
            raise Exception(f"yt-dlp failed to download the media: {error_msg}")

# Backwards-compatible alias
download_youtube = download_media

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QComboBox, QMessageBox, QProgressBar, QHBoxLayout,
    QSystemTrayIcon, QMenu, QAction, QDialog, QFileDialog,
    QSpacerItem, QSizePolicy, QCheckBox
)
from PyQt5.QtGui import QPalette, QColor, QFont, QPixmap, QIcon, QMovie
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QPoint
from datetime import datetime

# (Removed duplicate DownloadRecord class - using dataclass at top)

def save_download_history(record):
    """Save download record to history file"""
    history_file = os.path.join(str(Path.home()), '.yt_downloader_history.json')
    
    # Load existing history
    history = []
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            history = []
    
    # Add new record
    history.append(record.to_dict())
    
    # Keep only last 100 downloads
    history = history[-100:]
    
    # Save back
    try:
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to save download history: {e}")

# (Removed second organize_by_creator - unified above)

class DownloadWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)
    update_speed = pyqtSignal(str)

    def __init__(self, url, quality, download_subtitles=False):
        super().__init__()
        self.url = url
        self.quality = quality
        self.download_subtitles = download_subtitles

    def run(self):
        try:
            def progress_callback(percent):
                if 0 <= percent <= 100:
                    self.progress.emit(percent)
            progress_callback.update_speed = self.update_speed  # Attach signal
            
            # Enhanced URL validation and routing
            if is_image_url(self.url):
                # Direct image download
                downloaded_path = download_image(self.url, progress_callback)
                self.finished.emit(True, f"✅ Image downloaded: {os.path.basename(downloaded_path)}")
            elif is_video_url(self.url):
                # Video download via yt-dlp (YouTube, TikTok, etc.)
                record = download_youtube(self.url, self.quality, progress_callback, self.download_subtitles)
                platform_name = record.platform if record else "Video"
                creator_name = f" by {record.creator}" if record and record.creator else ""
                self.finished.emit(True, f"✅ {platform_name} download completed{creator_name}")
            elif is_twitter_media_url(self.url):
                # Try Twitter/X media download with fallback handling
                try:
                    record = download_youtube(self.url, self.quality, progress_callback, self.download_subtitles)
                    creator_name = f" by {record.creator}" if record and record.creator else ""
                    self.finished.emit(True, f"✅ Twitter media download completed{creator_name}")
                except Exception as twitter_error:
                    error_msg = str(twitter_error).lower()
                    if "not a video" in error_msg or "media #1 is not a video" in error_msg:
                        self.finished.emit(False, "❌ This Twitter post contains images, not videos. Twitter image downloads are not supported yet.")
                    elif "private" in error_msg or "protected" in error_msg:
                        self.finished.emit(False, "❌ Cannot download from private/protected Twitter accounts.")
                    elif "not found" in error_msg or "does not exist" in error_msg:
                        self.finished.emit(False, "❌ Twitter post not found or has been deleted.")
                    else:
                        raise twitter_error  # Re-raise if it's a different error
            else:
                raise ValueError("Unsupported URL - please provide a YouTube video, TikTok video, Twitter/X post, or direct image URL")
                
        except Exception as e:
            logging.error(str(e), exc_info=True)
            self.finished.emit(False, f"❌ Error: {str(e)}")

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Settings")
        self.setFixedSize(500, 640)
        layout = QVBoxLayout()

        # Apply dark/gray background so text is readable
        self.setStyleSheet("""
            QDialog {
                background-color: #181A1B;
            }
            QLabel {
                color: #DDDDDD;
            }
            QPushButton {
                background-color: #000000;
                color: #DDDDDD;
                border-radius: 6px;
                border: 1px solid #444444;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #222222;
                border: 1px solid #888888;
            }
            QCheckBox {
                color: #DDDDDD;
            }
        """)
        
        # Current folder display
        self.current_folder_label = QLabel(f"Current: {OUTPUT_DIR}")
        self.current_folder_label.setWordWrap(True)
        self.current_folder_label.setStyleSheet("color: #DDDDDD; padding: 5px;")
        layout.addWidget(self.current_folder_label)
        
        self.folder_btn = QPushButton("Change Download Folder")
        self.folder_btn.clicked.connect(self.change_folder)
        layout.addWidget(self.folder_btn)
        
        layout.addSpacing(10)
        
        # GIF customization section
        gif_label = QLabel("Custom GIF Animation:")
        gif_label.setStyleSheet("color: #DDDDDD; font-weight: bold;")
        layout.addWidget(gif_label)
        
        # Current GIF display
        current_settings = load_settings()
        custom_gif_path = current_settings.get('custom_gif_path', '')
        if custom_gif_path and os.path.exists(custom_gif_path):
            self.current_gif_label = QLabel(f"Current: {os.path.basename(custom_gif_path)}")
        else:
            self.current_gif_label = QLabel("Current: Default emoji fallback")
        self.current_gif_label.setWordWrap(True)
        self.current_gif_label.setStyleSheet("color: #DDDDDD; padding: 5px;")
        layout.addWidget(self.current_gif_label)
        
        self.gif_btn = QPushButton("Choose Custom GIF")
        self.gif_btn.clicked.connect(self.change_gif)
        layout.addWidget(self.gif_btn)
        
        self.reset_gif_btn = QPushButton("Reset to Default")
        self.reset_gif_btn.clicked.connect(self.reset_gif)
        layout.addWidget(self.reset_gif_btn)
        
        layout.addSpacing(10)
        
        # URL Icon customization section
        icon_label = QLabel("Global Custom URL Icon (used if dynamic disabled):")
        icon_label.setStyleSheet("color: #DDDDDD; font-weight: bold;")
        layout.addWidget(icon_label)
        
        # Current icon display
        custom_icon_path = current_settings.get('custom_icon_path', '')
        if custom_icon_path and os.path.exists(custom_icon_path):
            self.current_icon_label = QLabel(f"Current: {os.path.basename(custom_icon_path)}")
        else:
            self.current_icon_label = QLabel("Current: Default TV emoji (📺)")
        self.current_icon_label.setWordWrap(True)
        self.current_icon_label.setStyleSheet("color: #DDDDDD; padding: 5px;")
        layout.addWidget(self.current_icon_label)
        
        self.icon_btn = QPushButton("Choose Custom Icon")
        self.icon_btn.clicked.connect(self.change_icon)
        layout.addWidget(self.icon_btn)
        
        self.reset_icon_btn = QPushButton("Reset Icon to Default")
        self.reset_icon_btn.clicked.connect(self.reset_icon)
        layout.addWidget(self.reset_icon_btn)
        
        layout.addSpacing(10)

        # Per-platform icons section
        per_platform_label = QLabel("Per-Platform Icons (override emojis when dynamic enabled):")
        per_platform_label.setStyleSheet("color: #DDDDDD; font-weight: bold;")
        layout.addWidget(per_platform_label)

        current_settings = load_settings()
        youtube_path = current_settings.get('youtube_icon_path', '')
        tiktok_path = current_settings.get('tiktok_icon_path', '')
        twitter_path = current_settings.get('twitter_icon_path', '')

        def platform_row(label_text, key, existing_path):
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color:#DDDDDD")
            row.addWidget(lbl)
            status = QLabel(os.path.basename(existing_path) if existing_path and os.path.exists(existing_path) else "Default")
            status.setStyleSheet("color:#AAAAAA")
            row.addWidget(status)
            choose_btn = QPushButton("Choose")
            def choose():
                fp, _ = QFileDialog.getOpenFileName(self, f"Select {label_text} Icon", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.ico);;All Files (*)")
                if fp:
                    pm = QPixmap(fp)
                    if pm.isNull():
                        QMessageBox.warning(self, "Invalid", "Not a valid image file.")
                        return
                    st = load_settings(); st[f'{key}_icon_path'] = fp; save_settings(st)
                    status.setText(os.path.basename(fp))
                    if self.parent_app:
                        self.parent_app.reload_icon_settings()
                        self.parent_app.refresh_dynamic_icon()
            choose_btn.clicked.connect(choose)
            row.addWidget(choose_btn)
            reset_btn = QPushButton("Reset")
            def reset():
                st = load_settings(); st.pop(f'{key}_icon_path', None); save_settings(st)
                status.setText("Default")
                if self.parent_app:
                    self.parent_app.reload_icon_settings()
                    self.parent_app.refresh_dynamic_icon()
            reset_btn.clicked.connect(reset)
            row.addWidget(reset_btn)
            layout.addLayout(row)
        platform_row("YouTube", "youtube", youtube_path)
        platform_row("TikTok", "tiktok", tiktok_path)
        platform_row("Twitter", "twitter", twitter_path)

        layout.addSpacing(10)

        # Dynamic platform icon toggle
        current_settings = load_settings()
        self.dynamic_icons_checkbox = QCheckBox("Enable Dynamic Platform Icons (use per-platform icons if set)")
        self.dynamic_icons_checkbox.setChecked(current_settings.get('dynamic_icons_enabled', True))
        self.dynamic_icons_checkbox.setStyleSheet("color: #DDDDDD;")
        layout.addWidget(self.dynamic_icons_checkbox)
        
        # Save button
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.save_and_close)
        layout.addWidget(self.save_btn)
        
        self.setLayout(layout)

    def change_gif(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Select GIF Animation", 
            "", 
            "GIF Files (*.gif);;All Files (*)"
        )
        if file_path:
            try:
                # Test if the GIF can be loaded
                test_movie = QMovie(file_path)
                if not test_movie.isValid():
                    QMessageBox.warning(self, "Invalid File", "Selected file is not a valid GIF animation.")
                    return
                
                # Save the custom GIF path to settings
                settings = load_settings()
                settings['custom_gif_path'] = file_path
                save_settings(settings)
                
                # Update the display
                self.current_gif_label.setText(f"Current: {os.path.basename(file_path)}")
                
                # Update the main window's GIF if parent exists
                if self.parent_app:
                    self.parent_app.load_custom_gif(file_path)
                
                QMessageBox.information(self, "Success", "Custom GIF loaded successfully!")
                
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to load GIF: {str(e)}")

    def reset_gif(self):
        # Remove custom GIF from settings
        settings = load_settings()
        settings.pop('custom_gif_path', None)
        save_settings(settings)
        
        # Update display
        self.current_gif_label.setText("Current: Default emoji fallback")
        
        # Reset main window GIF if parent exists
        if self.parent_app:
            self.parent_app.reset_to_default_gif()
        
        QMessageBox.information(self, "Reset", "GIF reset to default!")

    def change_icon(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Select Icon Image", 
            "", 
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.ico);;All Files (*)"
        )
        if file_path:
            try:
                # Test if the image can be loaded
                test_pixmap = QPixmap(file_path)
                if test_pixmap.isNull():
                    QMessageBox.warning(self, "Invalid File", "Selected file is not a valid image.")
                    return
                
                # Save the custom icon path to settings
                settings = load_settings()
                settings['custom_icon_path'] = file_path
                save_settings(settings)
                
                # Update the display
                self.current_icon_label.setText(f"Current: {os.path.basename(file_path)}")
                
                # Update the main window's icon if parent exists
                if self.parent_app:
                    self.parent_app.load_custom_icon(file_path)
                
                QMessageBox.information(self, "Success", "Custom icon loaded successfully!")
                
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to load icon: {str(e)}")

    def reset_icon(self):
        # Remove custom icon from settings
        settings = load_settings()
        settings.pop('custom_icon_path', None)
        save_settings(settings)
        
        # Update display
        self.current_icon_label.setText("Current: Default TV emoji (📺)")
        
        # Reset main window icon if parent exists
        if self.parent_app:
            self.parent_app.reset_to_default_icon()
            self.parent_app.reload_icon_settings()
            self.parent_app.refresh_dynamic_icon()
        
        QMessageBox.information(self, "Reset", "Icon reset to default!")

    def change_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Folder")
        if folder:
            global OUTPUT_DIR
            OUTPUT_DIR = folder
            self.current_folder_label.setText(f"Current: {OUTPUT_DIR}")
            # Create directory if it doesn't exist
            try:
                os.makedirs(OUTPUT_DIR, exist_ok=True)
                # Test write permission
                test_file = os.path.join(OUTPUT_DIR, "test_write.tmp")
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
            except Exception as e:
                QMessageBox.warning(self, "Warning", f"Cannot write to folder: {str(e)}")
                return
    
    def save_and_close(self):
        # Save current settings
        settings = load_settings()
        settings['output_dir'] = OUTPUT_DIR
        settings['dynamic_icons_enabled'] = self.dynamic_icons_checkbox.isChecked()
        save_settings(settings)
        if self.parent_app:
            self.parent_app.reload_icon_settings()
            self.parent_app.refresh_dynamic_icon()
        self.accept()

    def load_custom_gif(self, gif_path):
        """Load a custom GIF and automatically resize it to fit the current size"""
        try:
            if os.path.exists(gif_path):
                # Stop current movie if any
                if hasattr(self, 'gif_movie') and self.gif_movie:
                    self.gif_movie.stop()
                
                # Load new GIF
                self.gif_movie = QMovie(gif_path)
                if self.gif_movie.isValid():
                    # Automatically scale to the current GIF label size
                    self.gif_movie.setScaledSize(self.gif_label.size())
                    self.gif_label.setMovie(self.gif_movie)
                    self.gif_movie.start()
                    return True
        except Exception as e:
            logging.error(f"Failed to load custom GIF: {e}")
        return False

    def reset_to_default_gif(self):
        """Reset GIF to default emoji"""
        if hasattr(self, 'gif_movie') and self.gif_movie:
            self.gif_movie.stop()
        
        # Reset to emoji fallback
        self.gif_label.setMovie(None)
        self.gif_label.setText("🎬")
        self.gif_label.setStyleSheet(f"color: {Config.NEON_GREEN}; font-size: 32px; background: transparent;")

class DownloaderApp(QWidget):
    def __init__(self):
        super().__init__()
        # Frameless window for fully custom black title area
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setWindowTitle("🖤 Universal Video Downloader")
        self.setFixedSize(Config.WINDOW_WIDTH, Config.WINDOW_HEIGHT)
        self._drag_pos = QPoint()
        # Load icon-related settings BEFORE building UI so load_url_icon has attributes
        self.reload_icon_settings()
        self.init_ui()
        self.apply_oled_black_theme()
        # Enable drag-and-drop for the URL input
        self.url_input.setAcceptDrops(True)
        self.url_input.installEventFilter(self)

        # Dynamic icon update on URL change
        self.url_input.textChanged.connect(self.on_url_changed)

        # System tray icon
        self.tray_icon = QSystemTrayIcon(self.style().standardIcon(self.style().SP_MediaPlay), self)
        tray_menu = QMenu()
        restore_action = QAction("Restore", self)
        restore_action.triggered.connect(self.showNormal)
        tray_menu.addAction(restore_action)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

        self.workers = []

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Custom black title bar ---
        title_bar = QWidget()
        title_bar.setFixedHeight(32)
        title_bar.setStyleSheet("background-color: #000000; border-bottom: 1px solid #333333;")
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(8, 0, 8, 0)
        tb_layout.setSpacing(6)

        title_label = QLabel("Media Downloader")
        title_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        title_label.setStyleSheet("color: #FFFFFF;")
        tb_layout.addWidget(title_label)
        tb_layout.addStretch(1)

        min_btn = QPushButton("-")
        min_btn.setFixedSize(24, 24)
        min_btn.setStyleSheet("background-color:#000000;color:#DDDDDD;border:none;")
        min_btn.clicked.connect(self.showMinimized)
        tb_layout.addWidget(min_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("background-color:#000000;color:#DDDDDD;border:none;")
        close_btn.clicked.connect(QApplication.instance().quit)
        tb_layout.addWidget(close_btn)

        layout.addWidget(title_bar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        # Slightly tighter top margin so text doesn't look cut off
        content_layout.setContentsMargins(30, 8, 30, 40)
        content_layout.setSpacing(6)

        self.setFixedSize(Config.WINDOW_WIDTH, Config.WINDOW_HEIGHT)

        # Video URL Label
        url_label = QLabel("Media URL")
        url_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        url_label.setStyleSheet("color: #FFFFFF;")
        content_layout.addWidget(url_label)
        content_layout.addSpacing(6)

        # Video URL Row
        url_row = QHBoxLayout()
        self.play_icon = QLabel()
        self.play_icon.setFixedSize(32, 32)
        # Prefer YouTube per-platform icon as the default if configured
        yt_default_path = self.platform_icon_paths.get(Platform.YOUTUBE, '')
        if yt_default_path and os.path.exists(yt_default_path) and self.load_custom_icon(yt_default_path):
            pass
        else:
            self.play_icon.setText("📺")
            self.play_icon.setStyleSheet("color: #FF0000; font-size: 20px; background: transparent;")
        url_row.addWidget(self.play_icon, alignment=Qt.AlignVCenter)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter YouTube video, Twitter/X post, or direct image URL")
        self.url_input.setMinimumHeight(36)
        self.url_input.setStyleSheet("border-radius: 6px; padding: 5px; background-color: #000000; color: #DDDDDD;")
        url_row.addWidget(self.url_input, alignment=Qt.AlignVCenter)
        content_layout.addLayout(url_row)
        # Slightly less space before "Video Quality" title
        content_layout.addSpacing(12)

        # Video Quality Label
        quality_label = QLabel("Video Quality")
        quality_label.setFont(QFont("Segoe UI", 11, QFont.Bold))  # Match font and size
        quality_label.setStyleSheet("color: #FFFFFF;")            # Match color
        content_layout.addWidget(quality_label)
        content_layout.addSpacing(6)

        # Quality Row
        quality_row = QHBoxLayout()
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["4k", "2k", "1080p", "720p", "480p", "360p", "best", "audio"])
        self.quality_combo.setMinimumHeight(30)
        self.quality_combo.setStyleSheet("border-radius: 6px; padding: 5px; background-color: #000000; color: #DDDDDD;")
        quality_row.addWidget(self.quality_combo)
        content_layout.addLayout(quality_row)
        content_layout.addSpacing(20)

        # Download Subtitles Checkbox
        self.subtitle_checkbox = QCheckBox("Download Subtitles (YouTube only)")
        self.subtitle_checkbox.setStyleSheet("""
            QCheckBox {
                color: #FFFFFF;
            }
            QCheckBox::indicator:checked {
                background-color: #39FF14;   /* Neon green when checked */
                border: 2px solid #39FF14;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid #39FF14;
            }
        """)
        content_layout.addWidget(self.subtitle_checkbox)
        content_layout.addSpacing(20)

        # Download Button
        self.download_btn = QPushButton("Download")
        self.download_btn.setMinimumHeight(40)
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.setStyleSheet("""
            QPushButton {
                background-color: #000000;   /* OLED black */
                color: #39FF14;              /* Neon green text */
                font-weight: bold;
                border-radius: 8px;
                border: 1px solid #39FF14;   /* Subtle neon border */
            }
            QPushButton:hover {
                background-color: #111111;
                border: 2px solid #39FF14;   /* Thicker border on hover */
            }
            QPushButton:pressed {
                background-color: #222222;
                border: 1px solid #39FF14;
            }
        """)
        content_layout.addWidget(self.download_btn)
        content_layout.addSpacing(16)

        # Download Progress Label (Neon Green)
        progress_label = QLabel("Download Progress")
        progress_label.setFont(QFont("Segoe UI", 10, QFont.Bold))  # Reduced from 11 to 10
        progress_label.setStyleSheet("color: #39FF14;")  # Neon green
        progress_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(progress_label)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(25)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #39FF14;
                border-radius: 12px;
                background-color: #000000;
                color: #39FF14;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #39FF14;
                border-radius: 10px;
                margin: 1px;
            }
        """)
        self.progress_bar.setValue(0)
        content_layout.addWidget(self.progress_bar)

        # --- Add your GIF here, right after the progress bar ---
        self.gif_label = QLabel()
        self.gif_label.setAlignment(Qt.AlignCenter)
        self.gif_label.setFixedSize(Config.GIF_SIZE, Config.GIF_SIZE)

        # Load custom GIF if available, otherwise try default paths
        self.load_gif_animation()
        
        content_layout.addWidget(self.gif_label, alignment=Qt.AlignCenter)

        # Load custom icon after UI is set up
        self.load_url_icon()

        # Speed and ETA Label
        self.speed_label = QLabel("")
        self.speed_label.setAlignment(Qt.AlignCenter)
        self.speed_label.setStyleSheet("color: #39FF14; font-size: 10pt;")
        content_layout.addWidget(self.speed_label)

        # Status Label
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFixedHeight(30)
        self.status_label.setStyleSheet("""
            QLabel {
                background-color: #000000;
                color: #DDDDDD;
                border-radius: 6px;
                padding: 5px;
                font-size: 12pt;
            }
        """)
        content_layout.addWidget(self.status_label)

        # Open Folder Button
        self.open_folder_btn = QPushButton("📂 Open Folder")
        self.open_folder_btn.setMinimumHeight(30)
        self.open_folder_btn.clicked.connect(self.open_download_folder)
        self.open_folder_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Config.OLED_BLACK};
                color: #FFEB3B;
                border-radius: 8px;
                font-weight: bold;
                border: 1px solid #FFEB3B;
                margin: 3px;
            }}
            QPushButton:hover {{
                background-color: #111111;
                border: 2px solid #FFEB3B;
            }}
            QPushButton:pressed {{
                background-color: #222222;
                border: 1px solid #FFEB3B;
            }}
        """)
        content_layout.addWidget(self.open_folder_btn)

        # Settings Button
        self.settings_btn = QPushButton("⚙️ Settings")
        self.settings_btn.setMinimumHeight(30)
        self.settings_btn.clicked.connect(self.open_settings)
        self.settings_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Config.OLED_BLACK};
                color: #DDDDDD;
                border-radius: 8px;
                font-weight: bold;
                border: 1px solid #DDDDDD;
                margin: 3px;
            }}
            QPushButton:hover {{
                background-color: #111111;
                border: 2px solid #DDDDDD;
            }}
            QPushButton:pressed {{
                background-color: #222222;
                border: 1px solid #DDDDDD;
            }}
        """)
        content_layout.addWidget(self.settings_btn)

        # Pin Button
        self.pin_btn = QPushButton("📌 Pin Window")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setMinimumHeight(30)
        self.pin_btn.clicked.connect(self.toggle_pin)
        self.pin_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Config.OLED_BLACK};
                color: #DDDDDD;
                border-radius: 8px;
                font-weight: bold;
                border: 1px solid #DDDDDD;
                margin: 3px;
            }}
            QPushButton:hover {{
                background-color: #111111;
                border: 2px solid #DDDDDD;
            }}
            QPushButton:pressed {{
                background-color: #222222;
                border: 1px solid #DDDDDD;
            }}
            QPushButton:checked {{
                background-color: #333333;
                border: 2px solid #39FF14;
                color: #39FF14;
            }}
        """)
        content_layout.addWidget(self.pin_btn)

        layout.addWidget(content)
        self.setLayout(layout)
        self.setFixedSize(480, 600)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def set_platform_icon(self, platform: Platform):
        """Set icon based on platform using per-platform images or fallback emojis."""
        if not self.dynamic_icons_enabled:
            # Use global icon if present
            if self.global_icon_path and os.path.exists(self.global_icon_path):
                self.load_custom_icon(self.global_icon_path)
            else:
                self.reset_to_default_icon()
            return

        # Try per-platform custom icon first
        chosen_path = self.platform_icon_paths.get(platform, '')
        if chosen_path and os.path.exists(chosen_path):
            if self.load_custom_icon(chosen_path):
                return

        # Fallback emojis/colors
        self.play_icon.setPixmap(QPixmap())
        if platform == Platform.YOUTUBE:
            self.play_icon.setText("📺")
            self.play_icon.setStyleSheet(f"color: {Config.YOUTUBE_RED}; font-size: 20px; background: transparent;")
        elif platform == Platform.TIKTOK:
            self.play_icon.setText("🎵")
            self.play_icon.setStyleSheet("color: #FFFFFF; font-size: 20px; background: transparent;")
        elif platform == Platform.TWITTER:
            self.play_icon.setText("🐦")
            self.play_icon.setStyleSheet("color: #1DA1F2; font-size: 20px; background: transparent;")
        elif platform == Platform.IMAGE:
            self.play_icon.setText("🖼️")
            self.play_icon.setStyleSheet("color: #DDDDDD; font-size: 20px; background: transparent;")
        else:
            # Default: prefer YouTube icon if configured, otherwise TV emoji
            yt_path = self.platform_icon_paths.get(Platform.YOUTUBE, '')
            if yt_path and os.path.exists(yt_path) and self.load_custom_icon(yt_path):
                return
            self.play_icon.setText("📺")
            self.play_icon.setStyleSheet("color: #FF0000; font-size: 20px; background: transparent;")

    def on_url_changed(self, text: str):
        platform = detect_platform(text)
        self.set_platform_icon(platform)

    def load_gif_animation(self):
        """Load GIF animation with priority: custom > default locations > emoji fallback"""
        # First check for custom GIF in settings
        current_settings = load_settings()
        custom_gif_path = current_settings.get('custom_gif_path', '')
        
        if custom_gif_path and os.path.exists(custom_gif_path):
            if self.load_custom_gif(custom_gif_path):
                return
        
        # Try default GIF locations if no custom GIF
        gif_paths = [
            Config.GIF_PATH,  # User's Downloads folder
            os.path.join(os.path.dirname(__file__), "giphy.gif"),  # Same folder as script
            os.path.join(os.path.dirname(__file__), "assets", "giphy.gif"),  # Assets folder
            "giphy.gif"  # Current directory
        ]
        
        gif_loaded = False
        for gif_path in gif_paths:
            try:
                if os.path.exists(gif_path):
                    self.gif_movie = QMovie(gif_path)
                    if self.gif_movie.isValid():
                        self.gif_movie.setScaledSize(self.gif_label.size())
                        self.gif_label.setMovie(self.gif_movie)
                        self.gif_movie.start()
                        gif_loaded = True
                        break
            except Exception as e:
                continue
        
        # Fallback to emoji if no GIF is found
        if not gif_loaded:
            logging.info("GIF not found in any location, using emoji fallback")
            self.reset_to_default_gif()

    def load_custom_gif(self, gif_path):
        """Load a custom GIF and automatically resize it to fit the current size"""
        try:
            if os.path.exists(gif_path):
                # Stop current movie if any
                if hasattr(self, 'gif_movie') and self.gif_movie:
                    self.gif_movie.stop()
                
                # Load new GIF
                self.gif_movie = QMovie(gif_path)
                if self.gif_movie.isValid():
                    # Automatically scale to the current GIF label size (80x80)
                    self.gif_movie.setScaledSize(self.gif_label.size())
                    self.gif_label.setMovie(self.gif_movie)
                    self.gif_movie.start()
                    return True
        except Exception as e:
            logging.error(f"Failed to load custom GIF: {e}")
        return False

    def reset_to_default_gif(self):
        """Reset GIF to default emoji"""
        if hasattr(self, 'gif_movie') and self.gif_movie:
            self.gif_movie.stop()
        
        # Reset to emoji fallback
        self.gif_label.setMovie(None)
        self.gif_label.setText("🎬")
        self.gif_label.setStyleSheet(f"color: {Config.NEON_GREEN}; font-size: 32px; background: transparent;")

    def load_url_icon(self):
        """Load custom URL icon if available"""
        # Defensive: ensure attributes exist (in case of future refactors)
        if not hasattr(self, 'dynamic_icons_enabled'):
            self.dynamic_icons_enabled = True
        if not hasattr(self, 'global_icon_path'):
            self.global_icon_path = ''
        # Only load global icon immediately if dynamic disabled
        if (not self.dynamic_icons_enabled) and self.global_icon_path and os.path.exists(self.global_icon_path):
            self.load_custom_icon(self.global_icon_path)
        # If no custom icon, keep the default emoji that's already set

    def load_custom_icon(self, icon_path):
        """Load a custom icon and automatically resize it to fit the current size"""
        try:
            if os.path.exists(icon_path):
                # Load and scale the image to fit the icon size (32x32)
                pixmap = QPixmap(icon_path)
                if not pixmap.isNull():
                    # Scale to fit while maintaining aspect ratio
                    scaled_pixmap = pixmap.scaled(
                        self.play_icon.size(), 
                        Qt.KeepAspectRatio, 
                        Qt.SmoothTransformation
                    )
                    self.play_icon.setPixmap(scaled_pixmap)
                    self.play_icon.setText("")  # Clear the emoji text
                    self.play_icon.setStyleSheet("background: transparent;")
                    return True
        except Exception as e:
            logging.error(f"Failed to load custom icon: {e}")
        return False

    def reset_to_default_icon(self):
        """Reset icon to default TV emoji"""
        self.play_icon.setPixmap(QPixmap())  # Clear any custom pixmap
        self.play_icon.setText("📺")
        self.play_icon.setStyleSheet("color: #FF0000; font-size: 20px; background: transparent;")
        # Do not clear per-platform icons; only global
        self.global_icon_path = ''

    def reload_icon_settings(self):
        s = load_settings()
        self.dynamic_icons_enabled = s.get('dynamic_icons_enabled', True)
        self.global_icon_path = s.get('custom_icon_path', '') if s.get('custom_icon_path') else ''
        self.platform_icon_paths = {
            Platform.YOUTUBE: s.get('youtube_icon_path', ''),
            Platform.TIKTOK: s.get('tiktok_icon_path', ''),
            Platform.TWITTER: s.get('twitter_icon_path', '')
        }

    def refresh_dynamic_icon(self):
        current_url = self.url_input.text().strip()
        platform = detect_platform(current_url)
        self.set_platform_icon(platform)

    def apply_oled_black_theme(self):
        oled_dark_gray = "#000000"

        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(oled_dark_gray))
        palette.setColor(QPalette.WindowText, QColor("#DDDDDD"))
        palette.setColor(QPalette.Base, QColor(oled_dark_gray))
        palette.setColor(QPalette.AlternateBase, QColor(oled_dark_gray))
        palette.setColor(QPalette.Text, QColor("#DDDDDD"))
        palette.setColor(QPalette.Button, QColor(oled_dark_gray))
        palette.setColor(QPalette.ButtonText, QColor("#DDDDDD"))
        palette.setColor(QPalette.Highlight, QColor("#444444"))
        palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        self.setPalette(palette)

    def toggle_theme(self):
        if self.palette().color(QPalette.Window) == QColor("#000000"):
            self.apply_light_theme()
        else:
            self.apply_oled_black_theme()

    def apply_light_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#FFFFFF"))
        palette.setColor(QPalette.WindowText, QColor("#222222"))
        palette.setColor(QPalette.Base, QColor("#FFFFFF"))
        palette.setColor(QPalette.AlternateBase, QColor("#F0F0F0"))
        palette.setColor(QPalette.Text, QColor("#222222"))
        palette.setColor(QPalette.Button, QColor("#F0F0F0"))
        palette.setColor(QPalette.ButtonText, QColor("#222222"))
        palette.setColor(QPalette.Highlight, QColor("#0078D7"))
        palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        self.setPalette(palette)

    def validate_url(self, url):
        """Validate and clean the URL"""
        if not url:
            return False, "Please enter a URL."
        
        # Basic URL validation
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                # Handle relative URLs - might be incomplete Twitter image URLs
                if url.startswith('/') and ('format=jpg' in url or 'format=png' in url or 'format=webp' in url):
                    return False, "Incomplete Twitter image URL. Please copy the full URL starting with https://pbs.twimg.com"
                return False, "Invalid URL format."
        except Exception:
            return False, "Invalid URL format."
        
        # Check for supported URLs
        if not (is_video_url(url) or is_image_url(url) or is_twitter_media_url(url)):
            return False, "Supported: YouTube videos, Twitter/X posts, or direct image URLs (jpg, png, gif, etc.)"
        
        return True, "URL is valid."

    def start_download(self):
        url = self.url_input.text().strip()
        quality = self.quality_combo.currentText()
        download_subtitles = self.subtitle_checkbox.isChecked()
        
        # Validate URL
        is_valid, message = self.validate_url(url)
        if not is_valid:
            QMessageBox.critical(self, "⚠️ Input Error", message)
            return
        
        # Check if it's an image URL and show appropriate message
        if is_image_url(url):
            self.status_label.setText("📸 Downloading image...")
        elif is_twitter_media_url(url):
            self.status_label.setText("🐦 Downloading Twitter media...")
        else:
            self.status_label.setText("📥 Downloading video...")
            
        self.download_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setStyleSheet(f"color: {Config.LIGHT_GRAY}; background-color: {Config.OLED_BLACK}; border-radius:6px;")
        
        worker = DownloadWorker(url, quality, download_subtitles)
        self.workers.append(worker)
        worker.finished.connect(lambda success, msg, w=worker: self.on_worker_finished(success, msg, w))
        worker.progress.connect(self.progress_bar.setValue)
        worker.update_speed.connect(self.speed_label.setText)
        worker.start()

    def on_worker_finished(self, success, message, worker):
        self.workers.remove(worker)
        self.download_finished(success, message)

    def download_finished(self, success, message):
        self.download_btn.setEnabled(True)
        self.status_label.setText(message)
        if success:
            self.progress_bar.setValue(100)
            self.status_label.setStyleSheet("color: #FFFFFF; background-color: #006400; border-radius:6px;")
            QMessageBox.information(self, "Download Complete", message)
            # Clear progress bar after successful download
            self.progress_bar.setValue(0)
            self.speed_label.setText("")  # Clear speed/ETA info
            # Clear the URL input field
            self.url_input.clear()
        else:
            self.progress_bar.setValue(0)
            self.status_label.setStyleSheet("color: #FFFFFF; background-color: #8B0000; border-radius:6px;")
            QMessageBox.critical(self, "Download Error", message)

    # Drag-and-drop support for URL input
    def eventFilter(self, source, event):
        if source == self.url_input:
            if event.type() == QEvent.DragEnter:
                if event.mimeData().hasUrls() or event.mimeData().hasText():
                    event.accept()
                    return True
            if event.type() == QEvent.Drop:
                if event.mimeData().hasUrls():
                    url = event.mimeData().urls()[0].toString()
                    self.url_input.setText(url)
                    return True
                elif event.mimeData().hasText():
                    self.url_input.setText(event.mimeData().text())
                    return True
        return super().eventFilter(source, event)

    # Open download folder in a cross-platform way
    def open_download_folder(self):
        import platform
        system = platform.system()
        if system == "Windows":
            subprocess.Popen(f'explorer "{OUTPUT_DIR}"')
        elif system == "Darwin":  # macOS
            subprocess.Popen(["open", OUTPUT_DIR])
        else:  # Linux and others
            subprocess.Popen(["xdg-open", OUTPUT_DIR])

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage("Downloader", "App minimized to tray.", QSystemTrayIcon.Information, 2000)

    def open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec_()

    def toggle_pin(self):
        if self.pin_btn.isChecked():
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            self.pin_btn.setText("📌 Unpin Window")
        else:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
            self.pin_btn.setText("📌 Pin Window")
        self.show()  # Needed to apply the window flag change

if __name__ == "__main__":
    app = QApplication(sys.argv)  
    window = DownloaderApp()
    window.show()
    sys.exit(app.exec_())
 
