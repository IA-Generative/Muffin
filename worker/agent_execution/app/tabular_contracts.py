"""What the pod exchanges with whoever asks it a question: the SQL and the sheets it may read, and what comes back.

The pod decides no access right: it reads the keys it is given, and nothing else. The sender (the agent) builds the
request from the files the user can read. Versioning as the OCR pods' contracts (app/ocr/contracts.py of
worker/document_process): a field added does not change SCHEMA_VERSION, readers ignore what they do not know, and a
pod refuses a request of a version newer than its own."""

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1

# A file is a schema of the SQL (f1, f2...), a sheet a table in it.
FILE_REF = re.compile(r"f[1-9][0-9]{0,2}")
# Where the typed copy of a sheet is (worker/document_process/app/tasks/_tabular_steps.py): documents/{collection}/
# {document}/tables/{n}.parquet.
TABLE_KEY = re.compile(
    r"documents/(?P<collection>[0-9a-fA-F-]{36})/(?P<document>[0-9a-fA-F-]{36})/tables/(?P<index>[0-9]{1,3})\.parquet"
)


class _Contract(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Column(_Contract):
    name: str = Field(max_length=500)
    sql_type: str = Field(max_length=200)


class Sheet(_Contract):
    name: str = Field(max_length=500)
    key: str = Field(max_length=300)
    columns: list[Column] = Field(default_factory=list, max_length=500)

    @field_validator("key")
    @classmethod
    def _a_table_key(cls, key: str) -> str:
        if not TABLE_KEY.fullmatch(key):
            raise ValueError("not the key of the typed copy of a sheet")
        return key


class File(_Contract):
    ref: str
    sheets: list[Sheet] = Field(min_length=1)

    @field_validator("ref")
    @classmethod
    def _a_reference(cls, ref: str) -> str:
        if not FILE_REF.fullmatch(ref):
            raise ValueError("a file is named f1, f2...")
        return ref


class QueryRequest(_Contract):
    schema_version: int = SCHEMA_VERSION
    sql: str = Field(max_length=20_000)
    # The collections the request is for: a key under another one is refused.
    collection_ids: list[str] = Field(min_length=1)
    files: list[File] = Field(min_length=1)

    @model_validator(mode="after")
    def _keys_stay_in_the_collections(self) -> "QueryRequest":
        if self.schema_version > SCHEMA_VERSION:
            raise ValueError(f"schema version {self.schema_version} is newer than {SCHEMA_VERSION}")
        allowed = {collection.lower() for collection in self.collection_ids}
        refs = [file.ref for file in self.files]
        if len(refs) != len(set(refs)):
            raise ValueError("two files cannot share a reference")
        for file in self.files:
            for sheet in file.sheets:
                match = TABLE_KEY.fullmatch(sheet.key)
                if match and match["collection"].lower() not in allowed:
                    raise ValueError("a key is outside the collections of the request")
        return self


class ResultColumn(_Contract):
    name: str
    type: str


class Table(_Contract):
    table: str
    columns: list[ResultColumn]


class QueryResult(_Contract):
    schema_version: int = SCHEMA_VERSION
    status: Literal["completed"] = "completed"
    columns: list[ResultColumn]
    rows: list[list[Any]]
    # The query had more rows (or more text) than are given back.
    truncated: bool
    duration_ms: int


class QueryFailure(_Contract):
    schema_version: int = SCHEMA_VERSION
    status: Literal["failed"] = "failed"
    # For whoever wrote the SQL to fix it.
    message: str
    # What can be queried, each table as the SQL must name it.
    tables: Annotated[list[Table], Field(default_factory=list)]
    duration_ms: int = 0
