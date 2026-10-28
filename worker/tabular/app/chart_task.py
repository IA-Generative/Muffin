"""One chart: the query of the agent runs again on the same sheets, and its result is drawn."""

import base64
import tempfile
import time
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from app.chart import ChartError, render_chart
from app.config import settings
from app.contracts import ChartFailure, ChartRequest, ChartResult, ResultColumn
from app.engine import QueryError, run_query
from app.limits import ChartLimits, QueryLimits
from app.storage import storage
from app.tasks import load_tables

# The image the caller is given must stay small enough for the broker: far above a chart at this fixed size.
MAX_PNG_BYTES = 2 * 1024 * 1024


def execute_chart(payload: dict, store=storage, work_dir: str | None = None) -> dict:
    """The outcome of one chart, as a ChartResult or a ChartFailure in JSON - never an exception for what the chart
    asks: the caller (a model) reads the message and corrects the spec."""
    started = time.monotonic()
    limits = ChartLimits()
    base = QueryLimits()
    # Same bounds as any query (time, memory, files), but more rows, and no cut on the size of the text.
    query_limits = QueryLimits(
        max_rows=limits.max_points,
        max_result_chars=50_000_000,
        timeout_seconds=base.timeout_seconds,
        memory_limit=base.memory_limit,
        threads=base.threads,
        max_table_bytes=base.max_table_bytes,
        max_files=base.max_files,
        max_sheets=base.max_sheets,
    )

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        request = ChartRequest.model_validate(payload)
    except ValidationError as error:
        fields = ", ".join(sorted({".".join(str(part) for part in e["loc"]) for e in error.errors()}))
        logger.warning(f"Refused a chart request: invalid {fields}")
        detail = "; ".join(e["msg"].removeprefix("Value error, ") for e in error.errors() if e["loc"][:1] == ("spec",))
        return ChartFailure(message=f"Demande invalide ({fields}). {detail}".strip()).model_dump(mode="json")

    columns: list[dict] = []
    try:
        with tempfile.TemporaryDirectory(dir=work_dir or settings.QUERY_WORK_DIR, prefix="chart_") as tmp:
            sandbox = Path(tmp)
            tables = load_tables(request, sandbox, query_limits, store)
            result = run_query(request.sql, tables, sandbox, query_limits)
        columns = result["columns"]
        png, width, height = render_chart(
            request.spec.model_dump(), columns, result["rows"], result["truncated"], limits
        )
        if len(png) > MAX_PNG_BYTES:
            raise ChartError("L'image dépasse la taille permise : réduis le nombre de points.")
    except (ChartError, QueryError) as error:
        return ChartFailure(
            message=str(error), columns=[ResultColumn(**c) for c in columns], duration_ms=elapsed()
        ).model_dump(mode="json")
    except Exception as error:
        logger.exception("A chart failed")
        return ChartFailure(
            message=f"Erreur inattendue : {type(error).__name__}",
            columns=[ResultColumn(**c) for c in columns],
            duration_ms=elapsed(),
        ).model_dump(mode="json")
    logger.info(f"Chart of {len(result['rows'])} row(s) in {elapsed()} ms")
    return ChartResult(
        png_base64=base64.b64encode(png).decode("ascii"),
        width=width,
        height=height,
        rows=len(result["rows"]),
        truncated=result["truncated"],
        duration_ms=elapsed(),
    ).model_dump(mode="json")
