import os
import json
import subprocess

from google.genai import types as genai_types

from derry.core.logger import get_logger

logger = get_logger(__name__)

# JSON-Schema type name → genai Type enum name
_TYPE_MAP = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
}


class CommandEngine:
    """
    Secure command executor backed by whitelist.json.

    Each whitelist entry declares:
      description  — shown to the model (function-calling tool description)
      parameters   — JSON Schema for the tool arguments
      argv         — fixed argv template; "{arg}" slots are filled from tool args
      defaults     — (optional) fallback values for non-required args

    Commands are executed via subprocess with a fixed argv (never shell=True),
    so tool arguments can never inject additional shell syntax.
    """

    def __init__(self):
        whitelist_path = os.path.join(os.path.dirname(__file__), "whitelist.json")
        try:
            with open(whitelist_path, "r") as f:
                self.whitelist = json.load(f)
            logger.info(f"Loaded {len(self.whitelist)} whitelisted commands.")
        except Exception as e:
            logger.error(f"Failed to load whitelist.json: {e}")
            self.whitelist = {}

    @staticmethod
    def _normalize(name: str, entry) -> dict:
        """Accept legacy plain-list entries: ["ls", "-la"] → no-arg tool."""
        if isinstance(entry, list):
            return {
                "description": f"Run the {name} system command.",
                "parameters": {"type": "object", "properties": {}},
                "argv": entry,
            }
        return entry

    # ── Tool schema (Gemini function calling) ─────────────────────────────────

    def get_tool(self):
        """Build a google-genai Tool with one FunctionDeclaration per whitelisted command."""
        declarations = []

        for name, raw in self.whitelist.items():
            entry = self._normalize(name, raw)
            params = entry.get("parameters", {"type": "object", "properties": {}})

            properties = {}
            for pname, pdef in (params.get("properties") or {}).items():
                ptype = _TYPE_MAP.get(pdef.get("type", "string"), "STRING")
                properties[pname] = genai_types.Schema(
                    type=genai_types.Type[ptype],
                    description=pdef.get("description", ""),
                )

            schema = genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties=properties,
                required=list(params.get("required", [])),
            )

            declarations.append(genai_types.FunctionDeclaration(
                name=name,
                description=entry.get("description", f"Run the {name} system command."),
                parameters=schema,
            ))

        logger.debug(f"Built Gemini tool schema: {len(declarations)} function declarations.")
        return genai_types.Tool(function_declarations=declarations)

    # ── Execution ─────────────────────────────────────────────────────────────

    def execute(self, command_name: str, args: dict | None = None) -> str:
        """
        Execute a whitelisted command by name, filling its argv template
        with the provided tool arguments. Returns the command output.
        """
        if command_name not in self.whitelist:
            logger.warning(f"Blocked unwhitelisted command attempt: {command_name}")
            return f"[Security Block] Command '{command_name}' is not in the whitelist."

        args = {k: v for k, v in (args or {}).items()}
        logger.debug(f"Tool call received: {command_name}({args})")

        entry = self._normalize(command_name, self.whitelist[command_name])
        defaults = entry.get("defaults", {})

        argv = []
        for slot in entry["argv"]:
            if isinstance(slot, str) and slot.startswith("{") and slot.endswith("}"):
                key = slot[1:-1]
                value = args.get(key, defaults.get(key))
                if value is None:
                    logger.error(f"Missing argument '{key}' for command '{command_name}'")
                    return f"Error: missing required argument '{key}' for {command_name}."
                value = os.path.expanduser(str(value))
                if "\x00" in value:
                    return f"Error: invalid argument for '{key}'."
                argv.append(value)
            else:
                argv.append(str(slot))

        logger.info(f"Executing whitelisted command: {' '.join(argv)}")
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=15,
            )

            output = result.stdout.strip()
            err_output = result.stderr.strip()

            if result.returncode == 0:
                logger.debug(f"Command success: {output[:200]}")
                return output if output else "Command executed successfully with no output."
            else:
                logger.error(f"Command failed (Code {result.returncode}): {err_output}")
                return f"Command failed: {err_output or output or f'exit code {result.returncode}'}"

        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out: {command_name}")
            return "Error: Command took too long to execute."
        except FileNotFoundError:
            logger.error(f"Command binary not found: {argv[0]}")
            return f"Error: '{argv[0]}' is not installed on this system."
        except Exception as e:
            logger.error(f"Unexpected error executing command: {e}")
            return f"Error: {str(e)}"
