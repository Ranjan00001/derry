import os
import json
import queue
import zipfile
import urllib.request
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal

from derry.core.logger import get_logger

logger = get_logger(__name__)


def _resolve_model_path() -> str:
    """
    Locate the Vosk model independent of the current working directory:
      1. DERRY_MODEL_PATH env var, if set
      2. repo-adjacent <repo>/model (source checkout, model already downloaded)
      3. ~/.cache/derry/model (fallback / download target)
    """
    env = os.environ.get("DERRY_MODEL_PATH")
    if env:
        return env
    repo_model = Path(__file__).resolve().parents[2] / "model"
    if repo_model.exists():
        return str(repo_model)
    return str(Path.home() / ".cache" / "derry" / "model")


class VoiceEngine(QThread):
    # Signals to communicate with the UI
    text_recognized = pyqtSignal(str)
    partial_text    = pyqtSignal(str)
    listening_started = pyqtSignal()
    listening_stopped = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, model_path: str | None = None, continuous: bool = False):
        super().__init__()
        self.model_path = model_path or _resolve_model_path()
        self._is_running = False
        self._continuous = continuous
        self._last_partial = ""
        self.q = queue.Queue()

    def set_continuous(self, enabled: bool):
        """Toggle continuous listening. False = walkie-talkie (stop after one phrase)."""
        self._continuous = enabled

    def _ensure_model(self):
        """Downloads a small vosk model into the cache dir if it doesn't exist."""
        if os.path.exists(self.model_path):
            return True

        target = Path(self.model_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Cannot create model cache dir: {e}")
            self.error_occurred.emit(f"Cannot create model cache dir: {e}")
            return False

        logger.info("Vosk model not found. Downloading small English model...")
        url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
        zip_path = str(target.parent / "vosk_model.zip")

        try:
            self.error_occurred.emit("Downloading Voice Model (~40MB)... Please wait.")
            urllib.request.urlretrieve(url, zip_path)

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(str(target.parent))

            extracted = target.parent / "vosk-model-small-en-us-0.15"
            if target.exists():
                # stale partial download — replace it
                import shutil
                shutil.rmtree(target)
            extracted.rename(target)
            os.remove(zip_path)
            logger.info("Model downloaded and extracted successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to download or extract model: {e}")
            self.error_occurred.emit(f"Failed to download voice model: {e}")
            return False

    def _audio_callback(self, indata, frames, time, status):
        """This is called (from a separate thread) for each audio block."""
        if status:
            logger.warning(f"SoundDevice status: {status}")
        self.q.put(bytes(indata))

    def run(self):
        self._is_running = True

        try:
            import sounddevice as sd
            import vosk
        except ImportError:
            self.error_occurred.emit("Missing audio dependencies: pip install vosk sounddevice")
            self._is_running = False
            return

        if not self._ensure_model():
            self._is_running = False
            return

        try:
            model = vosk.Model(self.model_path)

            # Use the default input device at its native rate — Vosk supports
            # any sample rate, so no resampling/forcing to 16 kHz is needed.
            device_info = sd.query_devices(sd.default.device[0], 'input')
            samplerate = int(device_info['default_samplerate'])

            rec = vosk.KaldiRecognizer(model, samplerate)

            self.listening_started.emit()
            logger.info(f"Started listening (device={device_info['name']}, sr={samplerate}, continuous={self._continuous})")

            with sd.RawInputStream(samplerate=samplerate, blocksize=8000, device=None,
                                   dtype='int16', channels=1, callback=self._audio_callback):
                while self._is_running:
                    try:
                        data = self.q.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    if rec.AcceptWaveform(data):
                        result = json.loads(rec.Result())
                        text = result.get("text", "").strip()
                        if text:
                            logger.debug(f"Recognized: {text}")
                            self._last_partial = ""
                            self.text_recognized.emit(text)
                            # In walkie-talkie mode stop after one phrase;
                            # in continuous mode keep listening until stopped manually.
                            if not self._continuous:
                                self._is_running = False
                    else:
                        # Live partial transcription for UI feedback
                        partial = json.loads(rec.PartialResult()).get("partial", "").strip()
                        if partial and partial != self._last_partial:
                            self._last_partial = partial
                            self.partial_text.emit(partial)

            self.listening_stopped.emit()

        except Exception as e:
            logger.error(f"Voice engine error: {e}")
            self.error_occurred.emit(str(e))
            self._is_running = False
            self.listening_stopped.emit()

    def stop(self):
        self._is_running = False
        self.wait()
