import sys
from PyQt6.QtWidgets import QApplication
from derry.core.logger import get_logger
from derry.ui.main_window import DerryMainWindow

logger = get_logger(__name__)

def main():
    logger.info("Starting Derry AI Agent...")
    
    app = QApplication(sys.argv)
    
    window = DerryMainWindow()
    window.show()
    
    exit_code = app.exec()
    logger.info("Derry exiting cleanly.")
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
