import logging
import re
import sys
from typing import Optional


class SensitiveFilter(logging.Filter):
    """Filters out potential API keys or secrets from log messages."""

    KEY_PATTERN = re.compile(r'(AIza[0-9A-Za-z\-_]{35})')

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.KEY_PATTERN.sub('[REDACTED_API_KEY]', record.msg)
        return True


def setup_logging(level: int = logging.INFO, log_file: Optional[str] = None) -> logging.Logger:
    """Sets up and returns the application logger."""
    logger = logging.getLogger("video_fixer")
    logger.setLevel(level)

    # Avoid duplicate handlers if already configured
    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        filter_ = SensitiveFilter()

        # Console handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        ch.addFilter(filter_)
        logger.addHandler(ch)

        # File handler if requested
        if log_file:
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(formatter)
            fh.addFilter(filter_)
            logger.addHandler(fh)

    return logger


logger = setup_logging()
