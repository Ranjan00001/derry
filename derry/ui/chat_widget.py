"""
chat_widget.py — Bubble-based chat UI with live streaming + Markdown rendering.
Architecture mirrored from PyGPT's message widget pattern.
"""
from markdown import markdown as _md_convert

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QTextBrowser, QLineEdit, QPushButton, QFrame, QLabel,
    QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer

from derry.core.logger import get_logger

logger = get_logger(__name__)

# ── Visual theme ──────────────────────────────────────────────────────────────
_BUBBLE_BG = {
    "You":          "#1A3050",
    "AI":           "#12302A",
    "System":       "#302A12",
    "System Error": "#3C1212",
}

_LABEL_COL = {
    "You":          "#82B1FF",
    "AI":           "#80CBC4",
    "System":       "#FFD54F",
    "System Error": "#EF9A9A",
}

# CSS injected into every markdown-rendered bubble
_MD_CSS = (
    "<style>"
    "body{font-family:sans-serif;font-size:13px;line-height:1.55;"
    "color:#E0E0E0;margin:0;padding:0;}"
    "p{margin:2px 0;}"
    "code{background:rgba(0,0,0,.5);padding:1px 5px;border-radius:3px;"
    "font-family:monospace;font-size:12px;}"
    "pre{background:rgba(0,0,0,.5);padding:8px;border-radius:6px;"
    "white-space:pre-wrap;}"
    "pre code{background:transparent;padding:0;}"
    "ul,ol{margin:4px 0;padding-left:20px;}"
    "li{margin:2px 0;}"
    "a{color:#82B1FF;}"
    "h1,h2,h3{margin:6px 0 2px;color:#CFD8DC;}"
    "</style>"
)


class ChatBubble(QFrame):
    """
    A single message bubble.

    Streaming workflow (mirrors PyGPT):
      1. append_chunk(chunk)  — fast plain-text insert while tokens arrive
      2. finalize()           — convert accumulated text to Markdown HTML

    Static workflow:
      1. set_text(text)       — render Markdown immediately (System/You bubbles)
    """

    speak_requested = pyqtSignal(object)  # emits the ChatBubble itself

    def __init__(self, sender: str, text: str = "", parent=None):
        super().__init__(parent)
        self._sender = sender
        self._raw: str = ""
        self._finalized = False
        self._thinking = False

        bg  = _BUBBLE_BG.get(sender, "#2A2A2A")
        lcl = _LABEL_COL.get(sender, "#AAAAAA")

        self.setStyleSheet(
            f"ChatBubble{{background:{bg};border-radius:10px;margin:2px 6px;}}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(10, 6, 10, 8)
        vbox.setSpacing(3)

        # Sender tag — transparent to mouse so window drag still works
        lbl = QLabel(sender)
        lbl.setStyleSheet(
            f"color:{lcl};font-size:11px;font-weight:bold;background:transparent;"
        )
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        header.addWidget(lbl)
        header.addStretch()

        self.speak_btn: QPushButton | None = None
        if sender == "AI":
            self.speak_btn = QPushButton("🔊")
            self.speak_btn.setFixedSize(20, 20)
            self.speak_btn.setToolTip("Speak this message")
            self.speak_btn.setStyleSheet(
                "QPushButton{background:transparent;border:none;font-size:12px;"
                "color:#80CBC4;border-radius:4px;}"
                "QPushButton:hover{background:rgba(255,255,255,.12);color:white;}"
            )
            self.speak_btn.clicked.connect(
                lambda: self.speak_requested.emit(self)
            )
            header.addWidget(self.speak_btn)

        vbox.addLayout(header)

        # Content renderer
        self.browser = QTextBrowser()
        self.browser.setReadOnly(True)
        self.browser.setFrameStyle(QFrame.Shape.NoFrame)
        self.browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet(
            "background:transparent;color:#E0E0E0;font-size:13px;border:none;"
        )
        self.browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.browser.setFixedHeight(24)

        # Auto-resize to content — no internal scrollbars ever
        self.browser.document().documentLayout().documentSizeChanged.connect(
            self._on_doc_size
        )

        vbox.addWidget(self.browser)

        if text:
            self.set_text(text)

    def _on_doc_size(self, size):
        h = max(int(size.height()) + 12, 24)
        self.browser.setFixedHeight(h)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_thinking(self, on: bool):
        """Show/replace content with a 'Thinking…' placeholder (cleared on first chunk)."""
        self._thinking = on
        if on:
            self._raw = ""
            self._finalized = False
            self.browser.setHtml(
                _MD_CSS
                + "<p style='color:#888;font-style:italic;'>Thinking…</p>"
            )

    def set_text(self, text: str):
        """Render text as Markdown HTML (replaces all existing content)."""
        self._raw = text
        self._thinking = False
        html = _md_convert(text, extensions=["fenced_code", "nl2br"])
        self.browser.setHtml(_MD_CSS + html)

    def append_chunk(self, chunk: str):
        """
        Append a raw streaming chunk as plain text (fast path).
        Call finalize() after streaming ends for proper Markdown rendering.
        """
        if self._thinking:
            # First real token arrived — drop the Thinking… placeholder
            self._thinking = False
            self.browser.clear()
        self._raw += chunk
        cursor = self.browser.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.browser.setTextCursor(cursor)
        self.browser.insertPlainText(chunk)
        self.browser.viewport().update()

    def finalize(self):
        """Convert accumulated streamed plain text to Markdown HTML."""
        if self._raw and not self._finalized:
            self.set_text(self._raw)
            self._finalized = True

    def clear_content(self):
        """Clear content — used when a command JSON was mid-streamed."""
        self._raw = ""
        self._finalized = False
        self.browser.clear()
        self.browser.setFixedHeight(24)

    def raw_text(self) -> str:
        """The accumulated (unsanitized) message text."""
        return self._raw

    def set_speaking(self, speaking: bool):
        """Flip the speaker icon while this bubble's text is being spoken."""
        if self.speak_btn is None:
            return
        self.speak_btn.setText("⏹️" if speaking else "🔊")
        self.speak_btn.setToolTip("Stop speaking" if speaking else "Speak this message")


class ChatWidget(QWidget):
    """Main chat interface: scrollable bubble list + input bar."""

    message_sent = pyqtSignal(str)
    mic_clicked  = pyqtSignal()
    speak_requested = pyqtSignal(object)  # ChatBubble whose 🔊 was clicked

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

        # Periodic scroll-to-bottom while AI is streaming
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(120)
        self._scroll_timer.timeout.connect(self._do_scroll)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Bubble scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameStyle(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("background:transparent;border:none;")

        self._container = QWidget()
        self._container.setStyleSheet("background:transparent;")
        self._blayout = QVBoxLayout(self._container)
        self._blayout.setContentsMargins(4, 6, 4, 4)
        self._blayout.setSpacing(6)
        self._blayout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

        # Input row
        row = QHBoxLayout()
        row.setContentsMargins(6, 4, 6, 6)
        row.setSpacing(5)

        self.mic_btn = QPushButton("🎤")
        self.mic_btn.setFixedSize(36, 36)
        self.mic_btn.setToolTip("Voice input — click to start, click again to stop")
        self.mic_btn.setStyleSheet(self._btn_css("#3A3A3A"))
        self.mic_btn.clicked.connect(self.mic_clicked.emit)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask Derry anything…")
        self.input_field.setStyleSheet(
            "QLineEdit{color:#E0E0E0;background:#3A3A3A;border-radius:7px;"
            "padding:6px 10px;font-size:13px;}"
            "QLineEdit:disabled{color:#666;background:#2A2A2A;}"
        )
        self.input_field.returnPressed.connect(self._on_send)

        self.send_btn = QPushButton("Send")
        self.send_btn.setFixedHeight(36)
        self.send_btn.setStyleSheet(self._btn_css("#2962FF"))
        self.send_btn.clicked.connect(self._on_send)

        row.addWidget(self.mic_btn)
        row.addWidget(self.input_field, 1)
        row.addWidget(self.send_btn)
        layout.addLayout(row)

    @staticmethod
    def _btn_css(bg: str) -> str:
        return (
            f"QPushButton{{background:{bg};color:white;border-radius:7px;"
            f"border:none;font-size:14px;padding:4px 10px;}}"
            f"QPushButton:disabled{{background:#3A3A3A;color:#555;}}"
        )

    # ── Bubble management ─────────────────────────────────────────────────────

    def add_bubble(self, sender: str, text: str = "") -> ChatBubble:
        """Add a bubble with pre-rendered text."""
        bubble = ChatBubble(sender, text)
        bubble.speak_requested.connect(self.speak_requested.emit)
        self._blayout.addWidget(bubble)
        self._scroll_later()
        return bubble

    def add_streaming_bubble(self, sender: str, thinking: bool = False) -> ChatBubble:
        """Add an empty bubble ready to receive live streaming chunks."""
        bubble = self.add_bubble(sender)
        if thinking:
            bubble.set_thinking(True)
        return bubble

    # ── Scroll helpers ────────────────────────────────────────────────────────

    def _scroll_later(self):
        QTimer.singleShot(80, self._do_scroll)

    def _do_scroll(self):
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def start_scroll_tracking(self):
        self._scroll_timer.start()

    def stop_scroll_tracking(self):
        self._scroll_timer.stop()
        self._do_scroll()

    # ── Input state ───────────────────────────────────────────────────────────

    def set_input_enabled(self, enabled: bool):
        self.input_field.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        if enabled:
            self.input_field.setFocus()

    def set_mic_listening(self, listening: bool):
        if listening:
            self.mic_btn.setText("⏹️")
            self.mic_btn.setStyleSheet(self._btn_css("#B71C1C"))
            self.mic_btn.setToolTip("Listening… click to stop")
        else:
            self.mic_btn.setText("🎤")
            self.mic_btn.setStyleSheet(self._btn_css("#3A3A3A"))
            self.mic_btn.setToolTip("Voice input — click to start, click again to stop")

    # ── Internal send ─────────────────────────────────────────────────────────

    def _on_send(self):
        text = self.input_field.text().strip()
        if text:
            self.input_field.clear()
            self.message_sent.emit(text)
