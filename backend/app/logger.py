import sys

from loguru import logger

from app.config import LoggingSettings

_settings = LoggingSettings()

logger.remove()
logger.add(
    sys.stdout,
    level=_settings.LOG_LEVEL,
    serialize=_settings.LOG_FORMAT == "json",
    colorize=_settings.LOG_FORMAT == "console",
)

__all__ = ["logger"]
