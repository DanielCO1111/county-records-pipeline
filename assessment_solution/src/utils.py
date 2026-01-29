import os
import re
import logging
from typing import Optional
from dotenv import load_dotenv

# Configure logging
logger = logging.getLogger(__name__)

def load_env_file():
    """Load .env file safely."""
    load_dotenv()

def get_env(key: str, required: bool = False, default: Optional[str] = None) -> Optional[str]:
    """
    Fetch environment variables safely.
    
    Args:
        key: The environment variable key.
        required: If True, log a warning if the key is missing.
        default: Default value if key is missing.
        
    Returns:
        The value of the environment variable or default.
    """
    value = os.getenv(key, default)
    if not value and required:
        logger.warning(f"Required environment variable '{key}' is missing.")
    return value

def is_valid_api_key(value: Optional[str]) -> bool:
    """
    Check if an API key is valid (not None, empty, or a placeholder).
    
    Args:
        value: The API key string to validate.
        
    Returns:
        True if valid, False otherwise.
    """
    if not value:
        return False
    
    placeholders = ["YOUR_API_KEY_HERE", "YOUR_OPENAI_API_KEY", "PASTE_KEY_HERE"]
    if any(p in value for p in placeholders):
        return False
        
    return len(value.strip()) > 10  # Basic length check for sanity

def normalize_doc_type(text: Optional[str]) -> str:
    """
    Normalize doc_type strings for matching purposes.
    
    Args:
        text: The raw doc_type string.
        
    Returns:
        A normalized string (uppercase, stripped, empty string if None).
    """
    if text is None:
        return ""
    return str(text).strip().upper()

def update_readme_report_block(readme_path: str, start_marker: str, end_marker: str, report_markdown: str):
    """
    Update a specific block in the README between markers.
    If markers are missing, append them to the end of the file.
    
    Args:
        readme_path: Path to the README.md file.
        start_marker: The start marker string (e.g., <!-- REPORT_START -->).
        end_marker: The end marker string (e.g., <!-- REPORT_END -->).
        report_markdown: The markdown content to inject between markers.
    """
    if not os.path.exists(readme_path):
        logger.error(f"README file not found at {readme_path}")
        return

    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        new_block = f"{start_marker}\n{report_markdown}\n{end_marker}"
        
        if start_marker in content and end_marker in content:
            # Replace existing block using regex for multi-line safety
            pattern = re.compile(f"{re.escape(start_marker)}.*?{re.escape(end_marker)}", re.DOTALL)
            new_content = pattern.sub(new_block, content)
        else:
            # Append to the end if markers are missing
            logger.info(f"Markers not found in {readme_path}. Appending to end.")
            new_content = content.rstrip() + "\n\n" + new_block + "\n"
        
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        logger.info(f"Successfully updated report block in {readme_path}")
        
    except Exception as e:
        logger.error(f"Failed to update README: {e}")

