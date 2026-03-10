"""ADB automation for phone apps (DeepSeek, Gemini).

Controls apps on the connected OPPO phone via ADB to:
- DeepSeek: send prompt → get text response (free, no API cost)
- Gemini: send prompt → get generated image (free, no API cost)
"""

import logging
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

ADB = "/opt/homebrew/bin/adb"
TEMP_DIR = Path("/tmp/adb_bot")
TEMP_DIR.mkdir(exist_ok=True)

# App package/activity
DEEPSEEK_PKG = "com.deepseek.chat"
DEEPSEEK_ACTIVITY = f"{DEEPSEEK_PKG}/.MainActivity"
GEMINI_PKG = "com.google.android.apps.bard"
GEMINI_ACTIVITY = f"{GEMINI_PKG}/.shellapp.BardEntryPointActivity"


class ADBBot:
    """Control phone apps via ADB for AI tasks."""

    def __init__(self):
        self._verify_device()

    # ── Low-level helpers ──────────────────────────────────────────

    def _run(self, *args, timeout: int = 30) -> str:
        """Run an adb shell command, return stdout."""
        cmd = [ADB, "shell"] + list(args)
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
            return r.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.warning(f"ADB command timed out: {args}")
            return ""

    def _run_host(self, *args, timeout: int = 30) -> str:
        """Run an adb host command (not shell)."""
        cmd = [ADB] + list(args)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()

    def _verify_device(self):
        """Check that a device is connected."""
        out = self._run_host("devices")
        if "device" not in out.split("\n")[-1] and "device" not in out:
            lines = [l for l in out.split("\n") if "device" in l and "List" not in l]
            if not lines:
                raise RuntimeError("No ADB device connected")
        logger.info("ADB device connected")

    def _tap(self, x: int, y: int):
        """Tap at coordinates."""
        self._run("input", "tap", str(x), str(y))

    def _long_press(self, x: int, y: int, duration_ms: int = 1000):
        """Long press at coordinates."""
        self._run("input", "swipe", str(x), str(y), str(x), str(y), str(duration_ms))

    def _swipe_up(self):
        """Swipe up to scroll down."""
        self._run("input", "swipe", "540", "1800", "540", "600", "300")

    def _swipe_down(self):
        """Swipe down to scroll up."""
        self._run("input", "swipe", "540", "600", "540", "1800", "300")

    def _key(self, keycode: str):
        """Send a keycode (e.g. KEYCODE_BACK, KEYCODE_ENTER)."""
        self._run("input", "keyevent", keycode)

    def _set_clipboard(self, text: str):
        """Set clipboard text via a temp file + am broadcast."""
        # Write text to phone file
        phone_path = "/sdcard/adb_bot_clip.txt"
        local_path = TEMP_DIR / "clip.txt"
        local_path.write_text(text, encoding="utf-8")
        self._run_host("push", str(local_path), phone_path)
        # Use am broadcast with service to set clipboard
        # Fallback: use input via base64 if clipper not available
        self._run("am", "broadcast", "-a", "clipper.set", "-e", "text", "$(cat /sdcard/adb_bot_clip.txt)")

    def _paste_via_keyevent(self):
        """Paste clipboard content using Ctrl+V keyevent."""
        # On Android: KEYCODE_PASTE = 279
        self._run("input", "keyevent", "279")

    def _input_long_text(self, target_x: int, target_y: int, text: str):
        """Input long text by writing to a file and using broadcast input.

        Flow: tap input → set clipboard → paste.
        """
        self._tap(target_x, target_y)
        time.sleep(0.5)

        # For short text, use input text directly
        if len(text) < 100 and text.isascii():
            escaped = text.replace(" ", "%s").replace("'", "\\'")
            self._run("input", "text", escaped)
            return

        # For long/unicode text: write file, use am to set clipboard, then paste
        phone_path = "/sdcard/adb_bot_input.txt"
        local_path = TEMP_DIR / "input.txt"
        local_path.write_text(text, encoding="utf-8")
        self._run_host("push", str(local_path), phone_path)

        # Try multiple clipboard methods
        # Method 1: service call
        self._run(
            "am", "broadcast",
            "-a", "android.intent.action.SEND",
            "--es", "text", text[:500],  # truncate for broadcast limits
        )

        # Method 2: Direct content provider approach
        # Use ADB shell to create a small script that sets clipboard
        script = (
            f'content write --uri content://com.android.shell.clipboard '
            f'--bind text:s:"{text[:200]}"'
        )

        # Most reliable: use input keyevent with ADB IME
        # First check if ADB keyboard is available
        ime_list = self._run("ime", "list", "-s")
        if "AdbKeyboard" in ime_list or "adbkeyboard" in ime_list.lower():
            self._run("am", "broadcast",
                       "-a", "ADB_INPUT_TEXT",
                       "--es", "msg", text)
            return

        # Fallback: chunk input via `input text` with URL encoding
        # This is slow but works for any text
        self._input_text_chunked(text)

    def _input_text_chunked(self, text: str):
        """Input text character by character using ADB input (fallback)."""
        # Use base64 to handle unicode
        import base64
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")

        # Write a helper script to the phone
        script = f"""
import base64, subprocess
text = base64.b64decode('{encoded}').decode('utf-8')
# Write to file for clipboard
with open('/sdcard/adb_bot_paste.txt', 'w') as f:
    f.write(text)
"""
        # Actually, simplest approach: write text to phone, then use xdotool equivalent
        # For Android, we'll use the broadcast approach with a helper app
        # or just type it slowly

        # Final fallback: use `input text` with escaped text, in chunks
        chunk_size = 50
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            # Escape special chars for shell
            escaped = chunk.replace("\\", "\\\\")
            escaped = escaped.replace("'", "'\\''")
            escaped = escaped.replace('"', '\\"')
            escaped = escaped.replace(" ", "%s")
            escaped = escaped.replace("&", "\\&")
            escaped = escaped.replace("|", "\\|")
            escaped = escaped.replace(";", "\\;")
            escaped = escaped.replace("\n", "\\n")
            if escaped:
                self._run("input", "text", f"'{escaped}'")
                time.sleep(0.1)

    def _screenshot(self, name: str = "screen") -> Path:
        """Take screenshot and pull to local."""
        phone_path = f"/sdcard/{name}.png"
        local_path = TEMP_DIR / f"{name}.png"
        self._run("screencap", "-p", phone_path)
        self._run_host("pull", phone_path, str(local_path))
        return local_path

    def _dump_ui(self) -> ET.Element:
        """Dump UI hierarchy and return root element."""
        self._run("uiautomator", "dump", "/sdcard/ui.xml")
        self._run_host("pull", "/sdcard/ui.xml", str(TEMP_DIR / "ui.xml"))
        tree = ET.parse(str(TEMP_DIR / "ui.xml"))
        return tree.getroot()

    def _find_element(self, root: ET.Element, **kwargs) -> dict | None:
        """Find a UI element by attributes. Returns bounds dict or None.

        Usage: _find_element(root, text="发送") or _find_element(root, desc="复制")
        """
        for node in root.iter("node"):
            match = True
            for key, val in kwargs.items():
                attr = "content-desc" if key == "desc" else key
                node_val = node.get(attr, "")
                if val not in node_val:
                    match = False
                    break
            if match:
                bounds = node.get("bounds", "")
                # Parse bounds "[x1,y1][x2,y2]"
                if bounds:
                    parts = bounds.replace("][", ",").strip("[]").split(",")
                    if len(parts) == 4:
                        x1, y1, x2, y2 = map(int, parts)
                        return {
                            "x": (x1 + x2) // 2,
                            "y": (y1 + y2) // 2,
                            "x1": x1, "y1": y1,
                            "x2": x2, "y2": y2,
                            "text": node.get("text", ""),
                            "desc": node.get("content-desc", ""),
                        }
        return None

    def _wait_for_element(self, timeout: int = 120, poll: int = 5, **kwargs) -> dict | None:
        """Wait for a UI element to appear. Returns element dict or None."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                root = self._dump_ui()
                elem = self._find_element(root, **kwargs)
                if elem:
                    return elem
            except Exception:
                pass
            time.sleep(poll)
        return None

    def _get_clipboard(self) -> str:
        """Read clipboard text from phone."""
        # Method: use service call to read clipboard
        out = self._run("service", "call", "clipboard", "2", "i32", "1",
                        "s16", "com.android.shell")
        # Parse the parcel output
        if "String16" in out:
            # Extract string between quotes
            import re
            match = re.search(r"'(.+?)'", out)
            if match:
                return match.group(1)

        # Alternative: read from a dumped file
        # Some ROMs support this
        return ""

    def _launch_app(self, activity: str):
        """Launch an app by activity name."""
        self._run("am", "start", "-n", activity)
        time.sleep(3)

    def _go_home(self):
        """Press home button."""
        self._key("KEYCODE_HOME")
        time.sleep(1)

    # ── DeepSeek ────────────────────────────────────────────────

    def deepseek_chat(self, prompt: str, timeout: int = 120) -> str:
        """Send a prompt to DeepSeek app and get the text response.

        Flow:
        1. Open DeepSeek → new chat
        2. Type prompt (via file + paste for long text)
        3. Send message
        4. Wait for response to complete (poll for 复制 button)
        5. Tap 复制 → read clipboard
        """
        logger.info(f"DeepSeek chat: {prompt[:50]}...")

        # Launch and start new chat
        self._launch_app(DEEPSEEK_ACTIVITY)
        time.sleep(2)

        # Tap "开启新对话" button
        root = self._dump_ui()
        new_chat = self._find_element(root, desc="开启新对话")
        if new_chat:
            self._tap(new_chat["x"], new_chat["y"])
            time.sleep(2)

        # Write prompt to phone file
        phone_prompt = "/sdcard/adb_bot_prompt.txt"
        local_prompt = TEMP_DIR / "prompt.txt"
        local_prompt.write_text(prompt, encoding="utf-8")
        self._run_host("push", str(local_prompt), phone_prompt)

        # Tap input field
        root = self._dump_ui()
        input_field = self._find_element(root, text="发消息")
        if not input_field:
            input_field = self._find_element(root, text="输入")
        if input_field:
            self._tap(input_field["x"], input_field["y"])
            time.sleep(0.5)

        # Input text: use ADB shell to read file and input via am broadcast
        # Most reliable for Chinese text: use the virtual keyboard
        # Chunk the text to avoid shell limits
        self._type_chinese_text(prompt)

        # Tap send button (or press Enter)
        time.sleep(0.5)
        root = self._dump_ui()
        send_btn = self._find_element(root, desc="发送")
        if send_btn:
            self._tap(send_btn["x"], send_btn["y"])
        else:
            # Try pressing Enter
            self._key("KEYCODE_ENTER")

        # Wait for response to complete
        # Poll for "复制" button which appears after generation finishes
        logger.info("Waiting for DeepSeek response...")
        copy_btn = self._wait_for_element(timeout=timeout, poll=8, desc="复制")

        if not copy_btn:
            logger.warning("DeepSeek: timeout waiting for response")
            # Try screenshot as fallback
            self._screenshot("ds_timeout")
            return "[DeepSeek 响应超时]"

        # Scroll to bottom to ensure we see the latest copy button
        time.sleep(2)

        # Re-dump to get the latest "复制" button position
        root = self._dump_ui()
        copy_btns = []
        for node in root.iter("node"):
            if node.get("content-desc", "") == "复制":
                bounds = node.get("bounds", "")
                parts = bounds.replace("][", ",").strip("[]").split(",")
                if len(parts) == 4:
                    x1, y1, x2, y2 = map(int, parts)
                    copy_btns.append({"x": (x1 + x2) // 2, "y": (y1 + y2) // 2, "y1": y1})

        # Use the LAST (bottom-most) copy button — that's the response
        if copy_btns:
            last_copy = max(copy_btns, key=lambda b: b["y1"])
            self._tap(last_copy["x"], last_copy["y"])
            time.sleep(1)

            # Read clipboard
            text = self._read_clipboard_via_file()
            if text:
                logger.info(f"DeepSeek response: {len(text)} chars")
                return text

        # Fallback: try to read text directly from UI dump
        return self._extract_response_from_ui(root)

    def _type_chinese_text(self, text: str):
        """Type Chinese text into the focused input field.

        Uses ADB Keyboard if available, otherwise falls back to
        broadcasting text via clipboard and pasting.
        """
        # Write text to phone
        phone_path = "/sdcard/adb_bot_input.txt"
        local_path = TEMP_DIR / "input.txt"
        local_path.write_text(text, encoding="utf-8")
        self._run_host("push", str(local_path), phone_path)

        # Method 1: Try ADB Keyboard broadcast
        ime_list = self._run("ime", "list", "-s")
        if "ADBKeyboard" in ime_list:
            # Switch to ADB keyboard, broadcast text, switch back
            current_ime = self._run("settings", "get", "secure", "default_input_method")
            self._run("ime", "set", "com.android.adbkeyboard/.AdbIME")
            time.sleep(0.3)
            self._run("am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "msg", text)
            time.sleep(0.5)
            if current_ime:
                self._run("ime", "set", current_ime)
            return

        # Method 2: Use content command to set clipboard, then paste
        # Write a small shell script to the phone that handles clipboard
        script_content = f'''#!/system/bin/sh
cat /sdcard/adb_bot_input.txt | am broadcast -a clipper.set --es text "$(cat /sdcard/adb_bot_input.txt)" > /dev/null 2>&1
'''
        script_local = TEMP_DIR / "set_clip.sh"
        script_local.write_text(script_content)
        self._run_host("push", str(script_local), "/sdcard/set_clip.sh")
        self._run("sh", "/sdcard/set_clip.sh")
        time.sleep(0.5)

        # Paste
        self._paste_via_keyevent()
        time.sleep(0.5)

        # If paste didn't work, try long press + paste from context menu
        root = self._dump_ui()
        paste_btn = self._find_element(root, text="粘贴")
        if paste_btn:
            self._tap(paste_btn["x"], paste_btn["y"])

    def _read_clipboard_via_file(self) -> str:
        """Read clipboard by having the phone write it to a file."""
        # Method: use am broadcast to get clipboard and write to file
        self._run("am", "broadcast", "-a", "clipper.get",
                  "--es", "output", "/sdcard/adb_bot_clipboard.txt")
        time.sleep(0.5)

        # Pull the file
        local_path = TEMP_DIR / "clipboard.txt"
        self._run_host("pull", "/sdcard/adb_bot_clipboard.txt", str(local_path))
        if local_path.exists():
            content = local_path.read_text(encoding="utf-8").strip()
            if content:
                return content

        # Fallback: parse service call output
        return self._get_clipboard()

    def _extract_response_from_ui(self, root: ET.Element) -> str:
        """Extract AI response text from UI dump (fallback)."""
        # Look for large text blocks that are not the prompt
        texts = []
        for node in root.iter("node"):
            text = node.get("text", "")
            if len(text) > 50:  # Skip short labels
                texts.append(text)

        if texts:
            # Return the longest text block (likely the response)
            return max(texts, key=len)
        return "[无法读取 DeepSeek 响应]"

    # ── Gemini ──────────────────────────────────────────────────

    def gemini_generate_image(self, prompt: str, output_path: Path,
                              timeout: int = 90) -> bool:
        """Send an image generation prompt to Gemini and save the result.

        Flow:
        1. Open Gemini → new chat
        2. Type prompt
        3. Wait for image to appear
        4. Screenshot the image area
        5. Crop and save

        Returns True if image was generated and saved.
        """
        logger.info(f"Gemini image: {prompt[:50]}...")

        # Launch Gemini
        self._launch_app(GEMINI_ACTIVITY)
        time.sleep(3)

        # Tap "发起新对话"
        root = self._dump_ui()
        new_chat = self._find_element(root, desc="发起新对话")
        if new_chat:
            self._tap(new_chat["x"], new_chat["y"])
            time.sleep(2)

        # Tap input field
        root = self._dump_ui()
        input_field = (
            self._find_element(root, text="问问 Gemini")
            or self._find_element(root, text="问问Gemini")
            or self._find_element(root, text="Message Gemini")
        )
        if input_field:
            self._tap(input_field["x"], input_field["y"])
            time.sleep(1)

        # Type the prompt
        self._type_chinese_text(prompt)
        time.sleep(0.5)

        # Find and tap send button
        root = self._dump_ui()
        send_btn = (
            self._find_element(root, desc="发送")
            or self._find_element(root, desc="Submit")
        )
        if send_btn:
            self._tap(send_btn["x"], send_btn["y"])
        else:
            self._key("KEYCODE_ENTER")

        # Wait for image to generate
        logger.info("Waiting for Gemini image generation...")
        img_elem = self._wait_for_element(
            timeout=timeout, poll=8, desc="生成的图片",
        )

        if not img_elem:
            # Also try English description
            img_elem = self._wait_for_element(timeout=30, poll=5, desc="Generated image")

        if not img_elem:
            logger.warning("Gemini: no image generated within timeout")
            self._screenshot("gm_timeout")
            return False

        time.sleep(2)  # Let image fully render

        # Screenshot the image area
        screen = self._screenshot("gm_image")

        # Crop the image area from the screenshot
        try:
            self._crop_image(
                screen, output_path,
                img_elem["x1"], img_elem["y1"],
                img_elem["x2"], img_elem["y2"],
            )
            logger.info(f"Gemini image saved: {output_path}")
            return True
        except Exception as e:
            logger.warning(f"Image crop failed, saving full screenshot: {e}")
            import shutil
            shutil.copy2(screen, output_path)
            return True

    def _crop_image(self, src: Path, dst: Path,
                    x1: int, y1: int, x2: int, y2: int):
        """Crop a region from an image using PIL."""
        from PIL import Image
        img = Image.open(src)
        cropped = img.crop((x1, y1, x2, y2))
        dst.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(dst)

    def gemini_generate_images(self, prompts: list[str],
                                output_dir: Path) -> list[Path]:
        """Generate multiple images, one per prompt.

        Returns list of successfully saved image paths.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        results = []

        for i, prompt in enumerate(prompts):
            out_path = output_dir / f"scene_{i + 1}.png"
            try:
                ok = self.gemini_generate_image(prompt, out_path)
                if ok and out_path.exists():
                    results.append(out_path)
                # Go back to start fresh for next image
                self._key("KEYCODE_BACK")
                time.sleep(2)
            except Exception as e:
                logger.warning(f"Image {i + 1} failed: {e}")

        return results
