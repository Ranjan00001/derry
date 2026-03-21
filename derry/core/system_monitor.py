import time
import subprocess
from PyQt6.QtCore import QThread, pyqtSignal

from derry.core.logger import get_logger

logger = get_logger(__name__)

class SystemMonitor(QThread):
    alert_triggered = pyqtSignal(str)

    def __init__(self, check_interval_sec=60):
        super().__init__()
        self.check_interval_sec = check_interval_sec
        self._is_running = False
        self.battery_warned = False

    def check_battery(self):
        try:
            # Note: /sys/class/power_supply/BAT0/capacity is standard on Linux 
            with open("/sys/class/power_supply/BAT0/capacity", "r") as f:
                capacity = int(f.read().strip())
                
            with open("/sys/class/power_supply/BAT0/status", "r") as f:
                status = f.read().strip()
                
            if status == "Discharging" and capacity < 20 and not self.battery_warned:
                self.alert_triggered.emit(f"Warning: Battery level is critically low ({capacity}%). Suggest plugging in.")
                self.battery_warned = True
            elif status == "Charging":
                self.battery_warned = False
                
        except Exception as e:
            # Battery might not exist (e.g., on a desktop)
            pass

    def run(self):
        self._is_running = True
        logger.info("System Monitor started.")
        while self._is_running:
            self.check_battery()
            
            # Additional checks like memory could reside here
            
            # Non-blocking sleep: check _is_running every second
            for _ in range(self.check_interval_sec):
                if not self._is_running:
                    break
                time.sleep(1)

    def stop(self):
        self._is_running = False
        self.wait()
