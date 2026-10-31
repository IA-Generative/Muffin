"""What the agent can query: the tabular files of the collections it searches, as the SQL worker (#432) names them.

Each file is a schema (`f1`, `f2`...) and each sheet a table of it, named as in the file, so a join between two files
is written as one between two sheets. The catalog is also what the request to the worker is built from, and from
nothing else: the keys it holds come from the backend's list of the documents this user may read.

A document that has no typed copy yet (indexed before #431, or whose copy failed) is listed as such and never
queried. What the files hold - their names, their columns, the values shown as examples - is data written by whoever
made them: the text here is for the model to read as data."""

from dataclasses import dataclass, field
from typing import Any

from app.agent.tabular_contracts import SCHEMA_VERSION


@dataclass(frozen=True)
class CatalogSheet:
    index: int
    # The name SQL gives the table (an unnamed sheet is `sheet_{n}`, as the worker names it).
    name: str
    rows: int
    truncated: bool
    key: str
    columns: list[dict[str, Any]]
    profile: list[dict[str, Any]]


@dataclass(frozen=True)
class CatalogFile:
    ref: str
    document_id: str
    name: str
    collection_id: str
    collection_name: str
    format: str
    sheets: list[CatalogSheet]


@dataclass
class Catalog:
    files: list[CatalogFile] = field(default_factory=list)
    # Tabular documents with nothing to query yet, and those left out because the worker joins at most so many files.
    pending: list[str] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, listings: list[tuple[dict[str, Any], list[dict[str, Any]]]], max_files: int) -> "Catalog":
        """`listings`: for each collection searched, the collection and the backend's list of its tabular documents."""
        catalog = cls()
        for collection, documents in listings:
            for document in documents:
                sheets = [
                    CatalogSheet(
                        index=sheet["index"],
                        name=sheet["name"] or f"sheet_{position}",
                        rows=sheet["rows"],
                        truncated=sheet.get("truncated", False),
                        key=sheet["parquet_key"],
                        columns=sheet.get("columns", []),
                        profile=sheet.get("profile", []),
                    )
                    for position, sheet in enumerate(document.get("sheets", []))
                ]
                if not sheets:
                    catalog.pending.append(document["name"])
                elif len(catalog.files) >= max_files:
                    catalog.omitted.append(document["name"])
                else:
                    catalog.files.append(
                        CatalogFile(
                            ref=f"f{len(catalog.files) + 1}",
                            document_id=str(document["id"]),
                            name=document["name"],
                            collection_id=str(collection["id"]),
                            collection_name=collection.get("name", ""),
                            format=document.get("format", ""),
                            sheets=sheets,
                        )
                    )
        return catalog

    def file(self, ref: str) -> CatalogFile | None:
        return next((file for file in self.files if file.ref == ref), None)

    def resolve(self, refs: list[str] | None) -> list[CatalogFile]:
        """The files a query reads: those it names, or all. Raises KeyError for a reference that is not a file."""
        if not refs:
            return list(self.files)
        resolved = []
        for ref in dict.fromkeys(refs):
            file = self.file(str(ref))
            if file is None:
                raise KeyError(ref)
            resolved.append(file)
        return resolved

    def request(self, sql: str, files: list[CatalogFile]) -> dict[str, Any]:
        """The worker's QueryRequest (app/tabular_contracts.py), as JSON."""
        return {
            "schema_version": SCHEMA_VERSION,
            "sql": sql,
            "collection_ids": sorted({file.collection_id for file in files}),
            "files": [
                {
                    "ref": file.ref,
                    "sheets": [
                        {"name": sheet.name, "key": sheet.key, "columns": sheet.columns} for sheet in file.sheets
                    ],
                }
                for file in files
            ],
        }

    def describe(self) -> str:
        """The files, sheets and columns, as the model reads them."""
        lines: list[str] = []
        for file in self.files:
            where = f" (collection « {file.collection_name} »)" if file.collection_name else ""
            lines.append(f"{file.ref} - {file.name}{where}")
            for sheet in file.sheets:
                cut = " - feuille tronquée : seules ses premières lignes sont interrogeables" if sheet.truncated else ""
                lines.append(f'  table "{file.ref}"."{_quote(sheet.name)}" - {sheet.rows} ligne(s){cut}')
                hints = {str(hint.get("name")): hint for hint in sheet.profile}
                for column in sheet.columns:
                    lines.append(f"    {_column_line(column, hints.get(str(column['name'])))}")
        if self.pending:
            lines.append(
                "Fichiers tabulaires pas encore interrogeables (à réindexer, jamais lus) : " + ", ".join(self.pending)
            )
        if self.omitted:
            lines.append("Fichiers laissés de côté (trop nombreux pour une requête) : " + ", ".join(self.omitted))
        return "\n".join(lines)


def _quote(name: str) -> str:
    return name.replace('"', '""')


def _column_line(column: dict[str, Any], hint: dict[str, Any] | None) -> str:
    line = f'"{_quote(str(column["name"]))}" {column["sql_type"]}'
    if not hint:
        return line
    parts = []
    if hint.get("distinct") is not None:
        parts.append(
            f"{'au moins ' if hint.get('distinct_exact') is False else ''}{hint['distinct']} valeur(s) distincte(s)"
        )
    if hint.get("null"):
        parts.append(f"{hint['null']} vide(s)")
    if hint.get("min") is not None and hint.get("max") is not None:
        parts.append(f"de {hint['min']} à {hint['max']}")
    if hint.get("top_values"):
        parts.append("ex. : " + ", ".join(str(value)[:40] for value in hint["top_values"]))
    return f"{line} - {' ; '.join(parts)}" if parts else line
