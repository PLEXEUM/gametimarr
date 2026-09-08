import os
import shutil
import json
from pathlib import Path
from app.utils.logger import get_logger
from app.utils.database import get_setting

logger = get_logger()


class FileManager:
    def __init__(self):
        self.folders = self._load_folders()

    def _load_folders(self) -> dict:
        """Load sport folders from settings."""
        folders_str = get_setting("sport_folders")
        if not folders_str:
            return {}
        
        try:
            # Try parsing as JSON
            return json.loads(folders_str)
        except:
            # Try parsing as key=value format
            folders = {}
            for item in folders_str.split(","):
                if "=" in item:
                    key, value = item.split("=", 1)
                    folders[key.strip()] = value.strip().strip('"')
            return folders

    def get_sport_folder(self, sport_slug: str) -> str:
        """Get the folder path for a sport."""
        return self.folders.get(sport_slug, "")

    def get_game_folder(self, sport_slug: str, game_name: str, date: str) -> str:
        """Generate a folder path for a specific game."""
        base = self.get_sport_folder(sport_slug)
        if not base:
            return ""

        # Create a clean folder name: "TeamA_vs_TeamB_MM-DD-YYYY"
        # This will be improved later
        return Path(base)

    def copy_file(self, source_path: str, destination_path: str) -> bool:
        """
        Copy a file from source to destination.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Ensure destination directory exists
            dest_dir = os.path.dirname(destination_path)
            os.makedirs(dest_dir, exist_ok=True)
            
            # Copy the file
            shutil.copy2(source_path, destination_path)
            logger.info(f"Copied: {source_path} -> {destination_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to copy file: {e}")
            return False

    def move_file(self, source_path: str, destination_path: str) -> bool:
        """
        Move a file from source to destination.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Ensure destination directory exists
            dest_dir = os.path.dirname(destination_path)
            os.makedirs(dest_dir, exist_ok=True)
            
            # Move the file
            shutil.move(source_path, destination_path)
            logger.info(f"Moved: {source_path} -> {destination_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to move file: {e}")
            return False

    def find_video_file(self, directory: str) -> str:
        """
        Find the first video file in a directory.
        
        Returns:
            str: Path to the video file, or empty string if none found
        """
        video_extensions = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.m4v', '.ts', '.m2ts'}
        
        if not os.path.exists(directory):
            return ""
        
        for root, dirs, files in os.walk(directory):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in video_extensions:
                    return os.path.join(root, file)
        
        return ""

    def get_destination_path(self, sport_slug: str, home_team: str, away_team: str, date: str) -> str:
        """
        Generate a destination path for a game.
        
        Example: /media/NCAAF/Auburn_vs_Baylor_09-05-2026.mp4
        """
        base = self.get_sport_folder(sport_slug)
        if not base:
            return ""
        
        # Clean team names for filename
        home_clean = home_team.replace(" ", "_")
        away_clean = away_team.replace(" ", "_")
        
        # Format date: MM-DD-YYYY from MM/DD/YYYY
        date_clean = date.replace("/", "-")
        
        filename = f"{home_clean}_vs_{away_clean}_{date_clean}"
        return os.path.join(base, filename)