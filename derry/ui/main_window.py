"""
main_window.py — Derry's always-on-top frameless window.
Key upgrade over original: streaming AIStreamTask + bubble lifecycle signals.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSystemTrayIcon, QMenu,
    QApplication, QSizeGrip,
)
from PyQt6.QtCore import Qt, QPoint, QThread, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QIcon

from derry.ui.chat_widget import ChatWidget, ChatBubble
from derry.core.logger import get_logger
from derry.core.ai_engine import AIEngine
from derry.core.command_engine import CommandEngine
from derry.core.voice_engine import VoiceEngine
from derry.core.system_monitor import SystemMonitor
from derry.core.tts_engine import TTSEngine
from derry.core.text_utils import text_to_speech_safe

logger = get_logger(__name__)


class AIStreamTask(QThread):
    """
    Runs Gemini streaming (with tool calls) in a background QThread.

    Signal protocol drives bubble lifecycle in the main thread:
      chunk_received  → append token to current streaming bubble
      bubble_finalize → finalize current bubble (with optional override text)
      new_bubble      → tool ran; create fresh AI bubble below system msg
      system_message  → add a System bubble (tool output)
      all_done        → whole task finished; re-enable input
    """
    chunk_received  = pyqtSignal(str)
    bubble_finalize = pyqtSignal(str)   # "" = keep streamed text; else override
    new_bubble      = pyqtSignal()
    system_message  = pyqtSignal(str)
    all_done        = pyqtSignal()

    def __init__(self, ai_engine: AIEngine, command_engine: CommandEngine, message: str):
        super().__init__()
        self.ai_engine      = ai_engine
        self.command_engine = command_engine
        self.message        = message

    def run(self):
        try:
            for event in self.ai_engine.stream_reply(self.message):
                if event[0] == "text":
                    self.chunk_received.emit(event[1])
                else:  # ("tool", name, args, result)
                    _, name, args, result = event
                    arg_s = ", ".join(f"{k}={v}" for k, v in (args or {}).items())
                    label = f"⚙️ {name}({arg_s})" if arg_s else f"⚙️ {name}"
                    self.bubble_finalize.emit(label)
                    # Truncate very long results so the follow-up prompt stays sane
                    truncated = result[:1200] + ("…" if len(result) > 1200 else "")
                    self.system_message.emit(f"⚙️ {truncated}")
                    # Ask for a fresh bubble for the follow-up answer
                    self.new_bubble.emit()
        except Exception as e:
            logger.error(f"AIStreamTask failed: {e}")
            self.chunk_received.emit(f"I encountered an unexpected error: {e}")

        self.all_done.emit()


class DerryMainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.old_pos: QPoint | None = None
        self._current_ai_bubble: ChatBubble | None = None
        self._speaking_bubble: ChatBubble | None = None

        # Core engines
        self.command_engine = CommandEngine()
        self.ai_engine      = AIEngine(self.command_engine)
        self.voice_engine   = VoiceEngine(continuous=True)
        self.tts_engine     = TTSEngine()
        self.system_monitor = SystemMonitor()
        self.system_monitor.alert_triggered.connect(self._on_system_alert)
        # self.system_monitor.start() # Stopping this for now

        self._setup_window()
        self._setup_ui()
        self._setup_tray()

    # ── Window ───────────────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(300, 400)
        self.resize(360, 560)

    def _setup_ui(self):
        container = QWidget()
        container.setObjectName("MainContainer")
        container.setStyleSheet(
            "#MainContainer{background:#1E1E1E;border-radius:14px;}"
        )
        self.setCentralWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(12, 8, 8, 4)
        header.setSpacing(4)

        title = QLabel("⚡ Derry")
        title.setStyleSheet(
            "color:#82B1FF;font-size:13px;font-weight:bold;background:transparent;"
        )
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header.addWidget(title)
        header.addStretch()

        self._min_btn = QPushButton("—")
        self._min_btn.setFixedSize(24, 24)
        self._min_btn.setStyleSheet(self._hdr_btn_css())
        self._min_btn.clicked.connect(self.hide)

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setStyleSheet(self._hdr_btn_css("#CC3333"))
        self._close_btn.clicked.connect(self.close_app)

        header.addWidget(self._min_btn)
        header.addWidget(self._close_btn)
        layout.addLayout(header)

        # Chat widget
        self.chat_widget = ChatWidget(self)
        self.chat_widget.message_sent.connect(self.handle_user_message)
        self.chat_widget.mic_clicked.connect(self.toggle_voice_input)
        self.chat_widget.speak_requested.connect(self._on_speak_requested)
        layout.addWidget(self.chat_widget, 1)

        # Resize grip (bottom-right corner)
        grip = QSizeGrip(container)
        layout.addWidget(
            grip, 0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
        )

        # Voice engine visual feedback
        self.voice_engine.listening_started.connect(
            lambda: self.chat_widget.set_mic_listening(True)
        )
        self.voice_engine.listening_stopped.connect(
            lambda: self.chat_widget.set_mic_listening(False)
        )
        self.voice_engine.text_recognized.connect(self._on_voice_text)
        self.voice_engine.partial_text.connect(self._on_voice_partial)
        self.voice_engine.error_occurred.connect(self._on_voice_error)

        # TTS: mute the mic while Derry speaks (no feedback loop)
        self.tts_engine.speaking_started.connect(
            lambda: self.voice_engine.set_muted(True)
        )
        self.tts_engine.speaking_finished.connect(
            lambda: self.voice_engine.set_muted(False)
        )
        self.tts_engine.speaking_finished.connect(self._on_speaking_finished)
        self.tts_engine.error_occurred.connect(self._on_tts_error)

        # Greeting
        if not self.ai_engine.api_key or self.ai_engine.api_key == "your_api_key_here":
            self.chat_widget.add_bubble(
                "System", "⚠️ GEMINI_API_KEY missing — check your .env file."
            )
        else:
            self.chat_widget.add_bubble("System", "Derry ready. How can I help?")

    @staticmethod
    def _hdr_btn_css(hover_col: str = "#555") -> str:
        return (
            "QPushButton{background:transparent;color:#888;font-weight:bold;"
            "border:none;border-radius:4px;}"
            f"QPushButton:hover{{color:white;background:{hover_col};}}"
        )

    # ── Tray ─────────────────────────────────────────────────────────────────

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon.fromTheme("system-run"))

        menu = QMenu()
        menu.addAction("Show Derry").triggered.connect(self.show)
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(self.close_app)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()
        self.tray_icon.activated.connect(self._on_tray_click)

    def _on_tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show() if self.isHidden() else self.hide()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close_app(self):
        if hasattr(self, "ai_task") and self.ai_task.isRunning():
            self.ai_task.terminate()
            self.ai_task.wait()
        if self.voice_engine.isRunning():
            self.voice_engine.stop()
        if self.tts_engine.isRunning():
            self.tts_engine.stop()
        if self.system_monitor.isRunning():
            self.system_monitor.stop()
        QApplication.quit()

    def _on_system_alert(self, msg: str):
        self.chat_widget.add_bubble("System", f"🔔 {msg}")
        self.tray_icon.showMessage(
            "Derry Alert", msg,
            QSystemTrayIcon.MessageIcon.Warning, 3000
        )

    # ── Message flow ──────────────────────────────────────────────────────────

    def handle_user_message(self, msg: str):
        logger.debug(f"User: {msg}")
        self.chat_widget.add_bubble("You", msg)
        self.chat_widget.set_input_enabled(False)
        self.chat_widget.start_scroll_tracking()

        # Create the first streaming AI bubble with a "Thinking…" placeholder;
        # the placeholder is cleared automatically on the first streamed chunk.
        self._current_ai_bubble = self.chat_widget.add_streaming_bubble("AI", thinking=True)

        self.ai_task = AIStreamTask(self.ai_engine, self.command_engine, msg)
        self.ai_task.chunk_received.connect(self._on_chunk)
        self.ai_task.bubble_finalize.connect(self._on_bubble_finalize)
        self.ai_task.new_bubble.connect(self._on_new_bubble)
        self.ai_task.system_message.connect(self._on_system_msg)
        self.ai_task.all_done.connect(self._on_all_done)
        self.ai_task.start()

    def _on_chunk(self, chunk: str):
        if self._current_ai_bubble:
            self._current_ai_bubble.append_chunk(chunk)

    def _on_bubble_finalize(self, override_text: str):
        if self._current_ai_bubble:
            if override_text:
                # Command was detected: show the clean text, not the raw JSON
                self._current_ai_bubble.set_text(override_text)
            else:
                # Normal response: convert streamed plain text to Markdown
                self._current_ai_bubble.finalize()
            self._current_ai_bubble = None

    def _on_new_bubble(self):
        """Called after a command executes — create a fresh AI bubble for the follow-up."""
        self._current_ai_bubble = self.chat_widget.add_streaming_bubble("AI")

    def _on_system_msg(self, msg: str):
        self.chat_widget.add_bubble("System", msg)

    def _on_all_done(self):
        # Safety net: finalize any lingering streaming bubble
        if self._current_ai_bubble:
            self._current_ai_bubble.finalize()
            self._current_ai_bubble = None
        self.chat_widget.set_input_enabled(True)
        self.chat_widget.stop_scroll_tracking()

    # ── Voice input ───────────────────────────────────────────────────────────

    def toggle_voice_input(self):
        if self.voice_engine.isRunning():
            self.voice_engine.stop()
        else:
            self.voice_engine.start()

    def _on_voice_text(self, text: str):
        """Route recognised speech: submit immediately if idle, else stage in input."""
        if self.chat_widget.send_btn.isEnabled():
            self.handle_user_message(text)
        else:
            self.chat_widget.input_field.setText(text)

    def _on_voice_partial(self, text: str):
        """Live partial transcription — show it in the input field while listening."""
        if self.chat_widget.send_btn.isEnabled():
            self.chat_widget.input_field.setText(text)

    def _on_voice_error(self, err: str):
        self.chat_widget.add_bubble("System Error", err)

    # ── Text-to-speech (per-bubble speaker button) ────────────────────────────

    def _on_speak_requested(self, bubble: ChatBubble):
        """Click 🔊 to speak a bubble, click ⏹ on the same bubble to stop."""
        if self._speaking_bubble is bubble:
            self.tts_engine.stop()
            return
        self.tts_engine.stop()
        text = text_to_speech_safe(bubble.raw_text())
        if not text:
            return
        self._speaking_bubble = bubble
        bubble.set_speaking(True)
        self.tts_engine.speak(text)

    def _on_speaking_finished(self):
        if self._speaking_bubble:
            self._speaking_bubble.set_speaking(False)
            self._speaking_bubble = None

    def _on_tts_error(self, err: str):
        self.chat_widget.add_bubble("System Error", err)
        if self._speaking_bubble:
            self._speaking_bubble.set_speaking(False)
            self._speaking_bubble = None

    # ── Draggable window ──────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.old_pos:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = None
