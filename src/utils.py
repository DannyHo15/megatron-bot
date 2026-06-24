import hashlib
import logging
import sys


def configure_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger("megatronbot")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
