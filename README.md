# Derry: Desktop AI Agent

A persistent, always-on-top AI assistant panel designed strictly for Linux. It acts as a smart companion integrated directly into the OS, bridging the gap between a standard conversational AI and a system-level automation tool.

## Installation

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
2. Install the package in editable mode:
   ```bash
   pip install -e .
   ```
3. Edit `.env` to add your Gemini API key.

## Features
- **Sticky UI:** Always-on-top, draggable chat panel.
- **Multimodal:** Text and voice input capabilities (Vosk).
- **Gemini AI:** Intelligent reasoning behind system actions.
- **Safe Execution Engine:** Securely runs whitelist-approved Linux commands.

## Running
Once installed, simply run:
```bash
derry
```
