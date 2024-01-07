import logging
import time
from logging.handlers import RotatingFileHandler

class SafeRotatingFileHandler(RotatingFileHandler):
    def __init__(self, *args, **kwargs):
        super(SafeRotatingFileHandler, self).__init__(*args, **kwargs)

    def _rotate(self, source, dest):
        """Override _rotate to handle PermissionError."""
        for _ in range(5):  # Retry up to 5 times
            try:
                super()._rotate(source, dest)
                break
            except PermissionError:
                logging.error(f"PermissionError: Unable to rotate log file. Retrying...")
                time.sleep(1)  # Wait for 1 second before retrying
            except Exception as e:
                logging.error(f"Unexpected error: {e}")
                break

def set_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler = SafeRotatingFileHandler('main.log', maxBytes=1024*1024*500, backupCount=3, delay=True)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger
