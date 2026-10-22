import inspect
import logging
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


class InterceptHandler(logging.Handler):
    """Hands what is logged through the standard `logging` (uvicorn, SQLAlchemy, httpx...) to loguru, so
    that everything comes out the same way - in JSON too (#305). loguru's own recipe."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # Back to the frame that called `logging`, so the line says where it was logged from.
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


# At LOG_LEVEL, not below: a library checks the level before building its debug lines.
logging.basicConfig(
    handlers=[InterceptHandler()],
    level=logging.getLevelNamesMapping().get(_settings.LOG_LEVEL.upper(), logging.INFO),
    force=True,
)
# uvicorn sets its loggers up before importing the app, with handlers of their own: through the root's.
for _name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
    _logger = logging.getLogger(_name)
    _logger.handlers = []
    _logger.propagate = True

__all__ = ["logger"]
