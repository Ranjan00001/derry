import os
import json
import logging
import warnings
from typing import Optional, Dict, Any
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")
import google.generativeai as genai

from derry.core.logger import get_logger

logger = get_logger(__name__)

# Load environment variables
load_dotenv()

class AIEngine:
    def __init__(self, command_engine=None):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            logger.error("GEMINI_API_KEY not found!")
            self.model = None
            return

        genai.configure(api_key=self.api_key)
        
        # System instructions dynamically injecting whitelist
        whitelist_keys = command_engine.get_whitelist_keys() if command_engine else []
        keys_str = ", ".join(whitelist_keys)
        
        system_instruction = f"""
        You are Derry, a persistent desktop AI assistant for a Linux desktop environment.
        You process user queries and dictate OS actions using a strict predefined list of intents.
        You ONLY have access to these exact commands/intents: [{keys_str}].
        If an action is needed, output a JSON block with the command request.
        For example:
        If you need to list files, your output must be:
        ```json
        {{
          "intent": "execute",
          "command": "list_files"
        }}
        ```
        If you execute a command, the output will be fed back to you. You should then analyze it and provide the final answer to the user.
        Do NOT output any command string directly (e.g. "ls -la"), ONLY use the abstract intents provided above.
        Keep your text responses concise and helpful. You are integrated directly into the OS.
        """
        
        self.model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=system_instruction
        )
        
        # We can implement a chat session for memory
        self.chat = self.model.start_chat()

    def generate_response(self, prompt: str) -> str:
        """Non-streaming call — used internally for command-intent detection."""
        if not self.model:
            return "Error: Gemini API key is not configured. Please check your .env file."
        
        try:
            logger.debug(f"Sending prompt to Gemini: {prompt}")
            response = self.chat.send_message(prompt)
            return response.text
        except Exception as e:
            logger.error(f"Error communicating with Gemini API: {e}")
            return f"I encountered an error while thinking: {str(e)}"

    def stream_response(self, prompt: str):
        """
        Yields text chunks from Gemini as they arrive.
        Mirrors PyGPT's streaming approach — no extra deps, uses the existing SDK.
        """
        if not self.model:
            yield "Error: GEMINI_API_KEY is not configured. Please check your .env file."
            return
        try:
            logger.debug(f"Streaming prompt to Gemini: {prompt[:80]}...")
            response = self.chat.send_message(prompt, stream=True)
            logger.info(response)
            for chunk in response:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield f"I encountered an error while thinking: {str(e)}"
