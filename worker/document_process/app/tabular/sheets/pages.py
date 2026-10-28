"""The text of a tabular document, as pages: one per sheet that has a table, in CSV.

Chunking skips a tabular file (a CSV is no good for vector search), so these pages are for being read - the page of a
document in the interface, and what a tool that reads a page is given. They are written from the typed copy, a batch of
rows at a time, and cut after `max_rows` rows: the data is in the Parquet, and it is SQL that reads it."""

import csv
import io
from pathlib import Path

import pyarrow.parquet as pq

_BATCH = 2000


def _text(value) -> str:
    return "" if value is None else str(value)


def csv_pages(folder: Path, analysis: dict, described: dict[int, dict], max_rows: int) -> list[str]:
    """The pages, in the order of the sheets: the CSV of the first `max_rows` rows of each. With several sheets, each
    page starts with the sheet's name."""
    sheets = {sheet["index"]: sheet for sheet in analysis["sheets"]}
    pages = []
    for index in sorted(described):
        buffer = io.StringIO()
        if len(described) > 1:
            buffer.write(f"# {sheets[index]['name']}\n")
        writer = csv.writer(buffer)
        writer.writerow([column["name"] for column in described[index]["columns"]])
        written, total = 0, described[index]["rows"]
        for batch in pq.ParquetFile(folder / f"{index}.parquet").iter_batches(batch_size=_BATCH):
            for row in zip(*(column.to_pylist() for column in batch.columns), strict=True):
                if written >= max_rows:
                    break
                writer.writerow([_text(value) for value in row])
                written += 1
            if written >= max_rows:
                break
        if written < total:
            buffer.write(f"# ... {total - written} more row(s) in this sheet, not repeated in this page\n")
        pages.append(buffer.getvalue())
    return pages
