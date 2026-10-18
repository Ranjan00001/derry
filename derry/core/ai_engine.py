import os
from dotenv import load_dotenv

from google import genai
from google.genai import types as genai_types

from derry.core.logger import get_logger

logger = get_logger(__name__)

# Load environment variables
load_dotenv()

MAX_TOOL_ROUNDS = 5

# Latest stable Gemini Flash model (GA Sept 2026). Override with GEMINI_MODEL in .env
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

SYSTEM_INSTRUCTION = """
You are Derry, a persistent desktop AI assistant for a Linux desktop environment.
You have a set of system tools for OS actions (opening apps, checking battery,
controlling volume, inspecting the system, and so on).

Rules:
- Call a tool whenever it helps answer the user's request; never invent shell
  commands or tool names that are not in your tool list.
- After a tool returns its output, summarise the result for the user in a short,
  friendly sentence.
- If no tool is needed, just answer directly.
- Keep text responses concise and helpful. You are integrated directly into the OS.
""".strip()


def _fmt_usage(usage) -> str:
    """Human-readable token accounting for a Gemini response."""
    if usage is None:
        return "tokens: unavailable"
    parts = [
        f"prompt={getattr(usage, 'prompt_token_count', '?')}",
        f"output={getattr(usage, 'candidates_token_count', '?')}",
        f"total={getattr(usage, 'total_token_count', '?')}",
    ]
    thoughts = getattr(usage, "thoughts_token_count", None)
    if thoughts:
        parts.append(f"thoughts={thoughts}")
    return " ".join(parts)


class AIEngine:
    def __init__(self, command_engine=None):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.command_engine = command_engine
        if not self.api_key:
            logger.error("GEMINI_API_KEY not found!")
            self.client = None
            self.chat = None
            return

        self.client = genai.Client(api_key=self.api_key)

        # Commands are exposed to the model as native function-calling tools —
        # the tool schema travels in the API `tools` field, not in prompt text.
        tools = None
        if command_engine:
            tools = [command_engine.get_tool()]

        self.config = genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=tools,
        )

        # Chat session keeps conversation memory
        self.chat = self.client.chats.create(model=DEFAULT_MODEL, config=self.config)
        logger.info(f"Gemini model: {DEFAULT_MODEL}")

    def generate_response(self, prompt: str) -> str:
        """Non-streaming call — simple synchronous helper."""
        if not self.client:
            return "Error: Gemini API key is not configured. Please check your .env file."

        try:
            logger.debug(f"→ Gemini request: {prompt}")
            response = self.chat.send_message(prompt)
            text = response.text
            logger.debug(f"← Gemini response: {text}")
            logger.debug(f"[usage] {_fmt_usage(response.usage_metadata)}")
            return text
        except Exception as e:
            logger.error(f"Error communicating with Gemini API: {e}")
            return f"I encountered an error while thinking: {str(e)}"

    def stream_reply(self, prompt: str):
        """
        Streams a reply, handling tool (function) calls.

        Yields event tuples:
          ("text", chunk)               — a fragment of the streamed answer
          ("tool", name, args, result)  — a tool was called; result is its output

        Every request sent to Gemini and every response received is logged at
        debug level, including per-round token usage.
        """
        if not self.chat:
            yield ("text", "Error: GEMINI_API_KEY is not configured. Please check your .env file.")
            return

        msg = prompt
        for round_no in range(1, MAX_TOOL_ROUNDS + 1):
            # ── outgoing: log exactly what we send ────────────────────────────
            if isinstance(msg, str):
                logger.debug(f"→ Gemini request (round {round_no}): {msg}")
            else:
                for part in msg:
                    fr = getattr(part, "function_response", None)
                    if fr:
                        logger.debug(
                            f"→ Gemini function_response (round {round_no}): "
                            f"{fr.name} -> {str(fr.response)[:500]}"
                        )

            text_parts: list[str] = []
            tool_calls: list[tuple[str, dict]] = []
            usage = None

            try:
                stream = self.chat.send_message_stream(msg)
                for chunk in stream:
                    if chunk.usage_metadata is not None:
                        usage = chunk.usage_metadata
                    try:
                        parts = chunk.candidates[0].content.parts
                    except (AttributeError, IndexError, TypeError, ValueError):
                        continue
                    for part in parts:
                        text = getattr(part, "text", None)
                        if text:
                            text_parts.append(text)
                            yield ("text", text)
                        fc = getattr(part, "function_call", None)
                        if fc and fc.name:
                            tool_calls.append((fc.name, dict(fc.args or {})))
            except Exception as e:
                logger.error(f"Streaming error (round {round_no}): {e}")
                yield ("text", f"I encountered an error while thinking: {str(e)}")
                return

            # ── incoming: log what came back and what it cost ─────────────────
            full_text = "".join(text_parts)
            if full_text:
                logger.debug(f"← Gemini response (round {round_no}): {full_text}")
            for name, args in tool_calls:
                logger.debug(f"← Gemini function_call (round {round_no}): {name}({args})")
            if not full_text and not tool_calls:
                logger.debug(f"← Gemini response (round {round_no}): <empty>")
            logger.debug(f"[usage] round {round_no} | {_fmt_usage(usage)}")

            if not tool_calls:
                return  # plain-text answer — stream complete

            # Execute every requested tool and feed the outputs back to the model
            response_parts = []
            for name, args in tool_calls:
                if self.command_engine:
                    result = self.command_engine.execute(name, args)
                else:
                    result = "[Command engine unavailable]"
                yield ("tool", name, args, result)
                response_parts.append(genai_types.Part.from_function_response(
                    name=name,
                    response={"output": result},
                ))

            msg = response_parts

        logger.warning("Tool round limit reached; aborting tool loop.")
        yield ("text", "\n(Stopped: too many tool calls in one request.)")
