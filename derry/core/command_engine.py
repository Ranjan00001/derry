import os
import json
import subprocess
import shlex
from derry.core.logger import get_logger

logger = get_logger(__name__)

class CommandEngine:
    def __init__(self):
        # Load strict whitelist of allowed commands.
        whitelist_path = os.path.join(os.path.dirname(__file__), "whitelist.json")
        try:
            with open(whitelist_path, "r") as f:
                self.whitelist = json.load(f)
            logger.info(f"Loaded {len(self.whitelist)} whitelisted commands.")
        except Exception as e:
            logger.error(f"Failed to load whitelist.json: {e}")
            self.whitelist = {}

    def get_whitelist_keys(self) -> list[str]:
        return list(self.whitelist.keys())

    def parse_and_execute(self, ai_response: str) -> tuple[bool, str, str]:
        """
        Parses the AI's response for a JSON block. If found, tries to execute the command.
        Returns (was_command: bool, execution_result: str, clean_response: str)
        """
        clean_response = ai_response
        was_command = False
        execution_result = ""

        # Check if there is a JSON code block in the response
        if "```json" in ai_response and "```" in ai_response.split("```json", 1)[1]:
            try:
                json_str = ai_response.split("```json", 1)[1].split("```", 1)[0].strip()
                data = json.loads(json_str)
                
                # We expect {"intent": "execute", "command": "something"}
                if data.get("intent") == "execute":
                    was_command = True
                    command_string = data.get("command")
                    logger.info(f"AI requested command: {command_string}")
                    
                    execution_result = self._execute_whitelist(command_string)
                    
                    # Clean up the output so we don't just dump raw json to the user UI
                    clean_response = ai_response.replace(f"```json\n{json_str}\n```", "").strip()
                    if not clean_response:
                        clean_response = f"Executing: {command_string}"
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from AI response: {e}")
                
        return was_command, execution_result, clean_response
        
    def _execute_whitelist(self, command_name: str) -> str:
        """Executes a command ONLY if it's in the whitelist."""
        if command_name not in self.whitelist:
            logger.warning(f"Blocked unwhitelisted command attempt: {command_name}")
            return f"[Security Block] Command '{command_name}' is not in the whitelist."
            
        cmd_args = self.whitelist[command_name]
        logger.info(f"Executing whitelisted command: {' '.join(cmd_args)}")
        
        try:
            result = subprocess.run(
                cmd_args, 
                capture_output=True, 
                text=True, 
                timeout=15
            )
            
            output = result.stdout.strip()
            err_output = result.stderr.strip()
            
            if result.returncode == 0:
                logger.debug(f"Command success: {output}")
                return output if output else "Command executed successfully with no output."
            else:
                logger.error(f"Command failed (Code {result.returncode}): {err_output}")
                return f"Command failed: {err_output}"
                
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out: {command_name}")
            return "Error: Command took too long to execute."
        except Exception as e:
            logger.error(f"Unexpected error executing command: {e}")
            return f"Error: {str(e)}"
