import logging
import sys

_initialized: bool = False


def get_logger(name: str = "lifeops") -> logging.Logger:
    global _initialized
    if not _initialized:
        root = logging.getLogger("lifeops")
        root.setLevel(logging.DEBUG)
        root.propagate = False
        if not root.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(logging.Formatter(
                "[%(asctime)s] %(levelname)-5s [%(name)s] %(message)s",
                datefmt="%H:%M:%S"
            ))
            root.addHandler(handler)
        _initialized = True

    return logging.getLogger(name)
