import os
import json
import queue
import zipfile
import urllib.request
from PyQt6.QtCore import QThread, pyqtSignal

from derry.core.logger import get_logger

logger = get_logger(__name__)

class VoiceEngine(QThread):
    # Signals to communicate with the UI
    text_recognized = pyqtSignal(str)
    listening_started = pyqtSignal()
    listening_stopped = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, model_path="model", continuous: bool = False):
        super().__init__()
        self.model_path = model_path
        self._is_running = False
        self._continuous = continuous
        self.q = queue.Queue()

    def set_continuous(self, enabled: bool):
        """Toggle continuous listening. False = walkie-talkie (stop after one phrase)."""
        self._continuous = enabled

    def _ensure_model(self):
        """Downloads a small vosk model if it doesn't exist."""
        if os.path.exists(self.model_path):
            return True
            
        logger.info("Vosk model not found. Downloading small English model...")
        url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
        zip_path = "vosk_model.zip"
        
        try:
            self.error_occurred.emit("Downloading Voice Model (~40MB)... Please wait.")
            urllib.request.urlretrieve(url, zip_path)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(".")
                
            os.rename("vosk-model-small-en-us-0.15", self.model_path)
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
            
            # Use default input device, 16000 Hz, mono
            device_info = sd.query_devices(sd.default.device[0], 'input')
            samplerate = int(device_info['default_samplerate'])
            
            # Vosk works best with 16000
            if samplerate != 16000:
                samplerate = 16000

            rec = vosk.KaldiRecognizer(model, samplerate)
            
            self.listening_started.emit()
            logger.info("Started listening for voice input...")

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
                            self.text_recognized.emit(text)
                            # In walkie-talkie mode stop after one phrase;
                            # in continuous mode keep listening until stopped manually.
                            if not self._continuous:
                                self._is_running = False
                            
            self.listening_stopped.emit()

        except Exception as e:
            logger.error(f"Voice engine error: {e}")
            self.error_occurred.emit(str(e))
            self._is_running = False
            self.listening_stopped.emit()

    def stop(self):
        self._is_running = False
        self.wait()
