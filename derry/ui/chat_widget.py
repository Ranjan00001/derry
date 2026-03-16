from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit, QPushButton
)
from PyQt6.QtCore import pyqtSignal

class ChatWidget(QWidget):
    # Signal emitted when user sends a message
    message_sent = pyqtSignal(str)
    mic_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Message history (read only)
        self.history_display = QTextEdit()
        self.history_display.setReadOnly(True)
        self.history_display.setStyleSheet("QTextEdit { border: none; background: transparent; color: white; }")
        layout.addWidget(self.history_display)
        
        # Input area layout
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(5, 5, 5, 5)
        
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Type a command...")
        self.input_field.setStyleSheet("QLineEdit { color: white; background-color: #3D3D3D; border-radius: 5px; padding: 5px; }")
        self.input_field.returnPressed.connect(self._on_send)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet("QPushButton { color: white; background-color: #505050; border-radius: 5px; padding: 5px 10px; }")
        self.send_btn.clicked.connect(self._on_send)
        
        # Mic button placeholder
        self.mic_btn = QPushButton("Mic")
        self.mic_btn.setFixedSize(50, 30)
        self.mic_btn.setStyleSheet("QPushButton { color: white; background-color: #505050; border-radius: 5px; font-weight: bold; }")
        self.mic_btn.clicked.connect(self.mic_clicked.emit)
        
        input_layout.addWidget(self.mic_btn)
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_btn)
        
        layout.addLayout(input_layout)
        
    def _on_send(self):
        text = self.input_field.text().strip()
        if text:
            self.append_message("You", text)
            self.input_field.clear()
            self.message_sent.emit(text)
            
    def append_message(self, sender: str, text: str):
        color = "#8AB4F8" if sender == "AI" else "#81C995"
        if sender == "System":
            color = "#FADB5F"
        
        html_msg = f'<b style="color:{color}">{sender}:</b> <span style="color:white">{text}</span>'
        self.history_display.append(html_msg)
        
        # Scroll to bottom
        scrollbar = self.history_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
