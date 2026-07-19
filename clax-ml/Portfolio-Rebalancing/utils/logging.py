# utils/logging.py
import logging

def get_logger(name):
    """
    Configures and returns a logger instance.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    return logging.getLogger(name)
