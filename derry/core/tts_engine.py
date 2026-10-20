"""
tts_engine.py — Local text-to-speech via Piper (en_US-lessac-medium).

Runs in its own QThread (same pattern as VoiceEngine). Synthesizes with the
piper-tts Python API and plays raw int16 PCM through sounddevice.
"""
import os
import queue
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from derry.core.logger import get_logger

logger = get_logger(__name__)

VOICE_ID = "en_US-lessac-medium"
_HF_BASE = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main"
    f"/en/en_US/lessac/medium/{VOICE_ID}"
)


def _voice_search_paths() -> list[Path]:
    """Ordered search locations for the .onnx voice, mirroring VoiceEngine."""
    paths: list[Path] = []
    env = os.environ.get("DERRY_PIPER_VOICE")
    if env:
        paths.append(Path(env))
    repo_dir = Path(__file__).resolve().parents[1] / "models" / "piper"
    paths.append(repo_dir / f"{VOICE_ID}.onnx")
    paths.append(Path.home() / ".cache" / "derry" / "piper" / f"{VOICE_ID}.onnx")
    return paths


def _resolve_voice_paths() -> tuple[Path, Path] | None:
    for onnx in _voice_search_paths():
        cfg = Path(str(onnx) + ".json")
        if onnx.exists() and cfg.exists():
            return onnx, cfg
    return None


def _download_voice() -> tuple[Path, Path] | None:
    """Download the voice model + config into the user cache dir."""
    target_dir = Path.home() / ".cache" / "derry" / "piper"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Cannot create piper cache dir: {e}")
        return None

    onnx = target_dir / f"{VOICE_ID}.onnx"
    cfg = Path(str(onnx) + ".json")
    try:
        logger.info(f"Downloading Piper voice {VOICE_ID} (~60MB)...")
        urllib.request.urlretrieve(f"{_HF_BASE}.onnx", onnx)
        urllib.request.urlretrieve(f"{_HF_BASE}.onnx.json", cfg)
        logger.info("Piper voice downloaded.")
        return onnx, cfg
    except Exception as e:
        logger.error(f"Failed to download Piper voice: {e}")
        return None


class TTSEngine(QThread):
    """Queues text utterances and speaks them via Piper, one at a time."""

    speaking_started  = pyqtSignal()
    speaking_finished = pyqtSignal()
    error_occurred    = pyqtSignal(str)

    def __init__(self, voice_path: str | None = None):
        super().__init__()
        self._voice_path = Path(voice_path) if voice_path else None
        self._q: queue.Queue[str] = queue.Queue()
        self._stop_flag = False
        self._broken = False

    # ── Public API ────────────────────────────────────────────────────────────

    def speak(self, text: str) -> None:
        """Queue `text` for synthesis + playback. Safe to call repeatedly."""
        if not text.strip() or self._broken:
            return
        self._stop_flag = False
        self._q.put(text)
        if not self.isRunning():
            self.start()

    def stop(self) -> None:
        """Abort current speech and clear the queue."""
        self._stop_flag = True
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

    # ── Worker ────────────────────────────────────────────────────────────────

    def _ensure_voice(self):
        try:
            from piper import PiperVoice
        except ImportError:
            self._broken = True
            self.error_occurred.emit("Missing TTS dependency: pip install piper-tts")
            return None

        if self._voice_path:
            onnx, cfg = self._voice_path, Path(str(self._voice_path) + ".json")
        else:
            resolved = _resolve_voice_paths()
            if resolved:
                onnx, cfg = resolved
            else:
                onnx, cfg = _download_voice() or (None, None)
                if onnx is None:
                    self._broken = True
                    self.error_occurred.emit(
                        "Piper voice model not found — set DERRY_PIPER_VOICE."
                    )
                    return None
        try:
            return PiperVoice.load(onnx, cfg)
        except Exception as e:
            logger.error(f"Failed to load Piper voice: {e}")
            self._broken = True
            self.error_occurred.emit(f"Failed to load Piper voice: {e}")
            return None

    def run(self):
        try:
            import sounddevice as sd
        except ImportError:
            self.error_occurred.emit("Missing audio dependency: pip install sounddevice")
            return

        voice = self._ensure_voice()
        if voice is None:
            return

        self.speaking_started.emit()
        try:
            while not self._stop_flag:
                try:
                    text = self._q.get(timeout=0.2)
                except queue.Empty:
                    break  # queue drained — exit; speak() restarts the thread

                logger.debug(f"TTS speak: {text[:80]}")
                try:
                    chunks = voice.synthesize(text)
                    first = next(chunks, None)
                    if first is None:
                        continue
                    with sd.RawOutputStream(
                        samplerate=first.sample_rate,
                        dtype="int16",
                        channels=1,
                    ) as stream:
                        stream.write(first.audio_int16_bytes)
                        for chunk in chunks:
                            if self._stop_flag:
                                break
                            stream.write(chunk.audio_int16_bytes)
                except Exception as e:
                    logger.error(f"TTS playback failed: {e}")
                    self.error_occurred.emit(f"TTS playback failed: {e}")
        finally:
            self.speaking_finished.emit()
