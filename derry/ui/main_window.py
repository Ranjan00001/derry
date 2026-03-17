from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtCore import Qt, QPoint, QThread, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QIcon
from derry.ui.chat_widget import ChatWidget
from derry.core.logger import get_logger
from derry.core.ai_engine import AIEngine
from derry.core.command_engine import CommandEngine
from derry.core.voice_engine import VoiceEngine
from derry.core.system_monitor import SystemMonitor

logger = get_logger(__name__)

class AITask(QThread):
    response_ready = pyqtSignal(str)
    command_executed = pyqtSignal(str, str)

    def __init__(self, ai_engine, command_engine, message):
        super().__init__()
        self.ai_engine = ai_engine
        self.command_engine = command_engine
        self.message = message

    def run(self):
        msg = self.message
        
        # Iterative loop: keep executing if AI sends commands
        for _ in range(5):  # Limit iterations to avoid infinite loops
            response = self.ai_engine.generate_response(msg)
            
            was_command, exec_result, clean_response = self.command_engine.parse_and_execute(response)
            
            if was_command:
                self.command_executed.emit(clean_response, exec_result)
                # Feed the execution result back to Gemini
                msg = f"Command Output:\n{exec_result}\n\nPlease proceed or format your final answer."
            else:
                self.response_ready.emit(response)
                break

class DerryMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.old_pos = None
        
        # Initialize Core Engines early
        self.command_engine = CommandEngine()
        self.ai_engine = AIEngine(self.command_engine)
        self.voice_engine = VoiceEngine()
        self.system_monitor = SystemMonitor()
        self.system_monitor.alert_triggered.connect(self._on_system_alert)
        self.system_monitor.start()
        
        self._setup_window()
        self._setup_ui()
        self._setup_tray()
        
    def _setup_window(self):
        # Frameless and Always On Top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(350, 500)
        
    def _setup_ui(self):
        # We use a container widget for styling the rounded corners
        central_container = QWidget()
        central_container.setObjectName("MainContainer")
        central_container.setStyleSheet(
            "#MainContainer { background-color: #2D2D2D; border-radius: 12px; }"
        )
        
        self.setCentralWidget(central_container)
        layout = QVBoxLayout(central_container)
        
        # Header bar (for dragging and close button)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addStretch()
        
        self.min_btn = QPushButton("—")
        self.min_btn.setFixedSize(24, 24)
        self.min_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #AAAAAA; font-weight: bold; border: none; }"
            "QPushButton:hover { color: #FFFFFF; }"
        )
        self.min_btn.clicked.connect(self.hide)
        header_layout.addWidget(self.min_btn)
        
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #AAAAAA; font-weight: bold; border: none; }"
            "QPushButton:hover { color: #FF5555; }"
        )
        self.close_btn.clicked.connect(self.close_app)
        header_layout.addWidget(self.close_btn)
        
        layout.addLayout(header_layout)
        
        self.chat_widget = ChatWidget(self)
        self.chat_widget.message_sent.connect(self.handle_user_message)
        self.chat_widget.mic_clicked.connect(self.toggle_voice_input)
        layout.addWidget(self.chat_widget)
        
        # Connect voice engine signals
        self.voice_engine.text_recognized.connect(self._on_voice_text)
        self.voice_engine.error_occurred.connect(self._on_voice_error)
        self.voice_engine.listening_started.connect(lambda: self.chat_widget.append_message("System", "Listening for voice command..."))
        
        # Initial greeting varies if API key is present
        if not self.ai_engine.api_key or self.ai_engine.api_key == "your_api_key_here":
            self.chat_widget.append_message("System", "Derry AI initialized. Warning: GEMINI_API_KEY is missing in .env.")
        else:
            self.chat_widget.append_message("System", "Derry AI initialized. Ready for commands.")
            
    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon.fromTheme("system-run"))
        
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show Derry")
        show_action.triggered.connect(self.show)
        
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.close_app)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
        self.tray_icon.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isHidden():
                self.show()
            else:
                self.hide()

    def close_app(self):
        if hasattr(self, 'ai_task') and self.ai_task.isRunning():
            self.ai_task.terminate()
            self.ai_task.wait()
        if self.voice_engine.isRunning():
            self.voice_engine.stop()
        if self.system_monitor.isRunning():
            self.system_monitor.stop()
        QApplication.quit()

    def _on_system_alert(self, msg: str):
        self.chat_widget.append_message("System", f"Alert: {msg}")
        self.tray_icon.showMessage("Derry AI Alert", msg, QSystemTrayIcon.MessageIcon.Warning, 3000)
        
    def handle_user_message(self, msg: str):
        logger.debug(f"User sent: {msg}")
        
        # We disable input visually or show a thinking indicator
        self.chat_widget.append_message("System", "thinking...")
        
        # Run AI generation in a separate thread so UI does not block
        self.ai_task = AITask(self.ai_engine, self.command_engine, msg)
        self.ai_task.response_ready.connect(self._on_ai_response)
        self.ai_task.command_executed.connect(self._on_command_executed)
        self.ai_task.start()
        
    def _on_ai_response(self, response: str):
        self.chat_widget.append_message("AI", response)
        
    def _on_command_executed(self, clean_response: str, exec_result: str):
        if clean_response:
            self.chat_widget.append_message("AI", clean_response)
        self.chat_widget.append_message("System", f"Command Result: {exec_result}")
        
    def toggle_voice_input(self):
        if self.voice_engine.isRunning():
            self.voice_engine.stop()
            self.chat_widget.append_message("System", "Voice listening stopped.")
        else:
            self.voice_engine.start()

    def _on_voice_text(self, text: str):
        self.chat_widget.input_field.setText(text)
        self.chat_widget.send_btn.click()
        
    def _on_voice_error(self, err: str):
        self.chat_widget.append_message("System Error", err)
        
    # --- Draggable Window Implementation ---
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = event.globalPosition().toPoint()
            
    def mouseMoveEvent(self, event: QMouseEvent):
        if hasattr(self, 'old_pos') and self.old_pos:
            delta = QPoint(event.globalPosition().toPoint() - self.old_pos)
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPosition().toPoint()
            
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = None
