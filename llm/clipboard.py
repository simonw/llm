import io
import sys
from typing import Optional, Union

from .models import Attachment
from .utils import mimetype_from_string


class ClipboardError(Exception):
    pass


def get_clipboard_image() -> Optional[bytes]:
    """
    Attempt to get image data from the clipboard.

    Returns:
        bytes: PNG image data if an image is on the clipboard
        None: if no image is available
    """
    if sys.platform == "win32":
        return _get_clipboard_image_windows()
    elif sys.platform == "darwin":
        return _get_clipboard_image_macos()
    else:
        return _get_clipboard_image_linux()


def get_clipboard_text() -> Optional[str]:
    """
    Get text from the clipboard.

    Returns:
        str: text content if available
        None: if clipboard is empty or doesn't contain text
    """
    if sys.platform == "win32":
        return _get_clipboard_text_windows()
    elif sys.platform == "darwin":
        return _get_clipboard_text_macos()
    else:
        return _get_clipboard_text_linux()


def _get_clipboard_image_windows() -> Optional[bytes]:
    """Get image from Windows clipboard using win32clipboard or PIL."""
    try:
        from PIL import ImageGrab

        img = ImageGrab.grabclipboard()
        if img is not None and hasattr(img, "save"):
            # It's a PIL Image
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            return buffer.getvalue()
        return None
    except ImportError:
        # Try win32clipboard as fallback
        try:
            import win32clipboard

            win32clipboard.OpenClipboard()
            try:
                # Try to get DIB format
                if win32clipboard.IsClipboardFormatAvailable(
                    win32clipboard.CF_DIB
                ):
                    data = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
                    # Convert DIB to PNG using PIL if available
                    try:
                        from PIL import Image

                        # DIB data needs special handling
                        img = Image.open(io.BytesIO(data))
                        buffer = io.BytesIO()
                        img.save(buffer, format="PNG")
                        return buffer.getvalue()
                    except Exception:
                        return None
                return None
            finally:
                win32clipboard.CloseClipboard()
        except ImportError:
            return None


def _get_clipboard_text_windows() -> Optional[str]:
    """Get text from Windows clipboard."""
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(
                win32clipboard.CF_UNICODETEXT
            ):
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                return data if data else None
            return None
        finally:
            win32clipboard.CloseClipboard()
    except ImportError:
        # Fallback to tkinter
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()
            try:
                text = root.clipboard_get()
                return text if text else None
            except tk.TclError:
                return None
            finally:
                root.destroy()
        except Exception:
            return None


def _get_clipboard_image_macos() -> Optional[bytes]:
    """Get image from macOS clipboard using pasteboard."""
    try:
        from PIL import ImageGrab

        img = ImageGrab.grabclipboard()
        if img is not None and hasattr(img, "save"):
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            return buffer.getvalue()
        return None
    except ImportError:
        # Fallback to using osascript/pbpaste for PNG
        import subprocess

        try:
            # Use osascript to check for image and get it as PNG
            script = """
            tell application "System Events"
                try
                    set theData to the clipboard as «class PNGf»
                    return theData
                on error
                    return ""
                end try
            end tell
            """
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
            )
            if result.returncode == 0 and result.stdout:
                # osascript returns hex-encoded data, need to decode
                return None  # Complex to parse, PIL is preferred
            return None
        except Exception:
            return None


def _get_clipboard_text_macos() -> Optional[str]:
    """Get text from macOS clipboard using pbpaste."""
    import subprocess

    try:
        result = subprocess.run(
            ["pbpaste"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
        return None
    except Exception:
        return None


def _get_clipboard_image_linux() -> Optional[bytes]:
    """Get image from Linux clipboard using xclip or PIL."""
    try:
        from PIL import ImageGrab

        img = ImageGrab.grabclipboard()
        if img is not None and hasattr(img, "save"):
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            return buffer.getvalue()
        return None
    except ImportError:
        pass

    # Fallback to xclip
    import subprocess

    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            capture_output=True,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
        return None
    except Exception:
        return None


def _get_clipboard_text_linux() -> Optional[str]:
    """Get text from Linux clipboard using xclip or xsel."""
    import subprocess

    # Try xclip first
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout if result.stdout else None
    except Exception:
        pass

    # Try xsel as fallback
    try:
        result = subprocess.run(
            ["xsel", "--clipboard", "--output"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout if result.stdout else None
    except Exception:
        pass

    return None


def resolve_clipboard() -> Union[Attachment, str]:
    """
    Get clipboard contents as an Attachment (for images) or string (for text).

    This function first tries to get an image from the clipboard. If no image
    is available, it falls back to text content.

    Returns:
        Attachment: if the clipboard contains an image
        str: if the clipboard contains text

    Raises:
        ClipboardError: if the clipboard is empty or inaccessible
    """
    # First, try to get an image
    image_data = get_clipboard_image()
    if image_data:
        # Determine the mimetype
        mimetype = mimetype_from_string(image_data)
        if mimetype is None:
            mimetype = "image/png"  # Default to PNG since we convert to PNG

        return Attachment(
            type=mimetype,
            path=None,
            url=None,
            content=image_data,
        )

    # Fall back to text
    text = get_clipboard_text()
    if text:
        return text

    raise ClipboardError(
        "Clipboard is empty or contains unsupported content. "
        "Supported content types: images (PNG, JPEG, etc.) and text."
    )
