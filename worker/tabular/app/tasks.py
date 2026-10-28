import tempfile
import time
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from app.celery_app import celery_app
from app.config import settings
from app.contracts import QueryFailure, QueryRequest, QueryResult
from app.engine import QueryError, TableSpec, listing, run_query
from app.limits import QueryLimits
from app.storage import storage


def load_tables(request: QueryRequest, work_dir: Path, limits: QueryLimits, store) -> list[TableSpec]:
    """Downloads the typed copy of every sheet of the request into the private folder, and names them for SQL."""
    if len(request.files) > limits.max_files:
        raise QueryError(f"Trop de fichiers dans la requête ({len(request.files)}) : {limits.max_files} au maximum.")
    if sum(len(file.sheets) for file in request.files) > limits.max_sheets:
        raise QueryError(f"Trop de feuilles dans la requête : {limits.max_sheets} au maximum.")
    specs: list[TableSpec] = []
    total = 0
    for file in request.files:
        names: set[str] = set()
        for number, sheet in enumerate(file.sheets):
            name = sheet.name or f"sheet_{number}"
            if name in names:
                raise QueryError(f"Le fichier {file.ref} a deux feuilles nommées « {name} ».")
            names.add(name)
            try:
                total += store.size(sheet.key)
                if total > limits.max_table_bytes:
                    raise QueryError(
                        f"Fichiers trop volumineux pour une seule requête (plus de {limits.max_table_bytes // 2**20} "
                        "Mo de données) : interrogez moins de fichiers."
                    )
                local = work_dir / f"{file.ref}_{number}.parquet"
                store.download(sheet.key, local)
            except QueryError:
                raise
            except Exception as error:  # a miss, a timeout: not the SQL's fault, but nothing can be queried
                raise QueryError(
                    f"La feuille « {name} » du fichier {file.ref} n'est pas lisible ({type(error).__name__})."
                ) from error
            specs.append(
                TableSpec(
                    ref=file.ref,
                    sheet=name,
                    path=local,
                    columns=[{"name": c.name, "sql_type": c.sql_type} for c in sheet.columns],
                )
            )
    return specs


def execute(payload: dict, store=storage, limits: QueryLimits | None = None, work_dir: str | None = None) -> dict:
    """The outcome of one query, as a QueryResult or a QueryFailure in JSON - never an exception for the SQL's fault:
    the caller (a model) reads the message and corrects it."""
    limits = limits or QueryLimits()
    started = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        request = QueryRequest.model_validate(payload)
    except ValidationError as error:
        # Not what the SQL did: the request is malformed or reaches outside its collections. Say which field only.
        fields = ", ".join(sorted({".".join(str(part) for part in e["loc"]) for e in error.errors()}))
        logger.warning(f"Refused a request: invalid {fields}")
        return QueryFailure(message=f"Demande invalide ({fields}).").model_dump(mode="json")

    tables: list[TableSpec] = []
    try:
        with tempfile.TemporaryDirectory(dir=work_dir or settings.QUERY_WORK_DIR, prefix="query_") as tmp:
            sandbox = Path(tmp)
            tables = load_tables(request, sandbox, limits, store)
            result = run_query(request.sql, tables, sandbox, limits)
    except QueryError as error:
        return QueryFailure(message=str(error), tables=listing(tables), duration_ms=elapsed()).model_dump(mode="json")
    except Exception as error:
        logger.exception("A query failed")
        return QueryFailure(
            message=f"Erreur inattendue : {type(error).__name__}", tables=listing(tables), duration_ms=elapsed()
        ).model_dump(mode="json")
    logger.info(f"Query over {len(tables)} table(s): {len(result['rows'])} row(s) in {elapsed()} ms")
    return QueryResult(**result, duration_ms=elapsed()).model_dump(mode="json")


@celery_app.task(name="app.tasks.run_query")
def run_sql(payload: dict) -> dict:
    """A SELECT over the sheets of a QueryRequest: a QueryResult, or a QueryFailure that says what to change."""
    return execute(payload)
