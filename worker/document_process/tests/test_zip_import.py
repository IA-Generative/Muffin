import hashlib
import importlib
import io
import os
import zipfile
from unittest.mock import MagicMock

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from app import task_logging, tasks
from app.config import settings
from app.storage import RangeReader
from app.zip_import import (
    ArchiveRejectedError,
    MemberSkippedError,
    ZipLimits,
    clean_part,
    count_entries,
    decode_name,
    extract_member,
    plan_import,
    split_safe_path,
)

LIMITS = ZipLimits(max_files=100, max_total_bytes=10_000_000, max_file_bytes=1_000_000, max_ratio=100, max_depth=5)


def _info(name: str, size: int = 10, compressed: int = 10, mode: int | None = None) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.file_size = size
    info.compress_size = compressed
    if mode is not None:
        info.external_attr = mode << 16
    return info


def _plan(*infos: zipfile.ZipInfo, limits: ZipLimits = LIMITS):
    return plan_import(list(infos), limits)


def _reasons(plan) -> dict[str, str]:
    return {item["path"]: item["reason"] for item in plan.skipped}


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class TestPaths:
    @pytest.mark.parametrize("raw", ["../evil.pdf", "a/../../evil.pdf", "/etc/evil.pdf", "C:/evil.pdf", "..\\evil.pdf"])
    def test_zip_slip_paths_are_refused(self, raw):
        assert split_safe_path(raw) is None

    def test_backslashes_and_dots_are_normalized(self):
        assert split_safe_path("a\\./b//c.pdf") == ["a", "b", "c.pdf"]

    def test_utf8_names_without_the_utf8_flag_are_recovered(self):
        info = zipfile.ZipInfo("café/résumé.pdf".encode().decode("cp437"))
        info.flag_bits = 0

        assert decode_name(info) == "café/résumé.pdf"

    def test_a_genuine_cp437_name_stays_as_decoded(self):
        info = zipfile.ZipInfo("\u2552.pdf")  # box-drawing char: valid CP437, not valid UTF-8 once encoded
        info.flag_bits = 0

        assert decode_name(info) == "\u2552.pdf"

    def test_names_are_cleaned_and_shortened_keeping_the_extension(self):
        assert clean_part("caf\u0065\u0301\x00\u200b.pdf") == "café.pdf"
        long_name = clean_part("x" * 300 + ".pdf")
        assert len(long_name) == 200 and long_name.endswith(".pdf")


class TestPlan:
    def test_folders_become_sub_collections_parents_first(self):
        plan = _plan(_info("a/b/doc.pdf"), _info("a/c.md"), _info("racine.txt"))

        assert plan.folders == [("a",), ("a", "b")]
        assert {(f.folder, f.name) for f in plan.files} == {
            (("a", "b"), "doc.pdf"),
            (("a",), "c.md"),
            ((), "racine.txt"),
        }

    def test_a_folder_with_nothing_importable_creates_nothing(self):
        plan = _plan(_info("empty/"), _info("only-junk/notes.exe"), _info("kept/doc.pdf"))

        assert plan.folders == [("kept",)]

    def test_a_folder_holding_only_folders_is_still_created(self):
        plan = _plan(_info("outer/inner/doc.pdf"))

        assert plan.folders == [("outer",), ("outer", "inner")]

    def test_unsafe_and_unwanted_members_are_listed_as_skipped(self):
        plan = _plan(
            _info("../evil.pdf"),
            _info("link.pdf", mode=0o120777),
            _info(".hidden/doc.pdf"),
            _info("nested.zip"),
            _info("program.exe"),
            _info("empty.pdf", size=0),
            _info("huge.pdf", size=2_000_000),
            _info("bomb.pdf", size=500_000, compressed=100),
            _info("a/b/c/d/e/f/too-deep.pdf"),
        )

        assert plan.files == []
        assert _reasons(plan) == {
            "../evil.pdf": "chemin en dehors de l'archive",
            "link.pdf": "lien symbolique",
            ".hidden/doc.pdf": "fichier ou dossier caché",
            "nested.zip": "archive imbriquée",
            "program.exe": "type de fichier non pris en charge",
            "empty.pdf": "fichier vide",
            "huge.pdf": "fichier trop volumineux",
            "bomb.pdf": "taux de compression suspect",
            "a/b/c/d/e/f/too-deep.pdf": "dossier trop profond",
        }

    def test_os_metadata_is_dropped_silently(self):
        plan = _plan(_info("__MACOSX/a/._doc.pdf"), _info("a/._doc.pdf"), _info("a/.DS_Store"), _info("a/Thumbs.db"))

        assert plan.files == [] and plan.skipped == []

    def test_too_many_files_refuses_the_whole_archive(self):
        limits = ZipLimits(max_files=2, max_total_bytes=10_000, max_file_bytes=1_000, max_ratio=100, max_depth=5)

        with pytest.raises(ArchiveRejectedError, match="3 fichiers"):
            _plan(_info("a.pdf"), _info("b.pdf"), _info("c.pdf"), limits=limits)

    def test_declared_total_over_the_limit_refuses_the_whole_archive(self):
        limits = ZipLimits(max_files=10, max_total_bytes=100, max_file_bytes=1_000, max_ratio=100, max_depth=5)

        with pytest.raises(ArchiveRejectedError):
            _plan(_info("a.pdf", size=60, compressed=60), _info("b.pdf", size=60, compressed=60), limits=limits)

    def test_without_limits_neither_the_number_of_files_nor_their_size_counts(self):
        infos = [_info(f"a/b/c/d/e/f/g/f{i}.pdf", size=500_000_000, compressed=400_000_000) for i in range(5000)]

        plan = _plan(*infos, limits=ZipLimits())

        assert len(plan.files) == 5000 and plan.skipped == []

    def test_by_default_only_the_compression_ratio_is_limited(self):
        assert (
            settings.ZIP_IMPORT_MAX_FILES,
            settings.ZIP_IMPORT_MAX_TOTAL_BYTES,
            settings.ZIP_IMPORT_MAX_FILE_BYTES,
            settings.ZIP_IMPORT_MAX_DEPTH,
        ) == (None, None, None, None)
        assert settings.ZIP_IMPORT_MAX_RATIO == 100


class TestExtractMember:
    def test_reads_a_member_within_its_cap(self):
        archive = zipfile.ZipFile(io.BytesIO(_zip({"doc.pdf": b"%PDF-1.4 hello"})))

        sink = io.BytesIO()

        assert extract_member(archive, archive.getinfo("doc.pdf"), cap=1000, sink=sink) == 14
        assert sink.getvalue() == b"%PDF-1.4 hello"

    def test_stops_past_the_cap_whatever_the_header_says(self):
        archive = zipfile.ZipFile(io.BytesIO(_zip({"doc.pdf": b"x" * 5000})))

        with pytest.raises(MemberSkippedError, match="plus volumineux"):
            extract_member(archive, archive.getinfo("doc.pdf"), cap=100, sink=io.BytesIO(), chunk_size=64)

    def test_a_corrupted_member_is_skipped(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as writer:
            writer.writestr("doc.pdf", b"y" * 2000)
        raw = bytearray(buffer.getvalue())
        # Stored, not compressed: the content sits as is right after the local header - altering
        # it leaves the archive readable but fails the member's CRC check.
        start = raw.index(b"y" * 100)
        raw[start : start + 100] = b"z" * 100
        archive = zipfile.ZipFile(io.BytesIO(bytes(raw)))

        with pytest.raises(MemberSkippedError, match="corrompu"):
            extract_member(archive, archive.getinfo("doc.pdf"), cap=10_000, sink=io.BytesIO())


class _FakeStorage:
    """RustFS as the import uses it: the archive read by ranges, the plan stored beside it, the files streamed."""

    def __init__(self, archive: bytes) -> None:
        self.objects = {"imports/i.zip": archive}
        self.uploaded: dict[str, bytes] = {}
        self.put_object = MagicMock(
            side_effect=lambda key, data, content_type=None: self.objects.__setitem__(key, data)
        )
        self.upload_fileobj = MagicMock(
            side_effect=lambda key, fileobj, content_type: self.uploaded.__setitem__(key, fileobj.read())
        )

    def open_seekable(self, key: str):
        return io.BytesIO(self.objects[key])

    def get_object(self, key: str) -> bytes:
        return self.objects[key]


class _FakeBackend(MagicMock):
    """The backend's bookkeeping of the batches of an import, as the real one does it (#334)."""

    def start(self, root: str = "root") -> "_FakeBackend":
        self.expected, self.done, self.results, self.status = [], [], {}, "running"
        self.begin_collection_import.return_value = {"archive_key": "imports/i.zip", "root_collection_id": root}
        self.is_imported_duplicate.return_value = False
        created = iter(f"col-{i}" for i in range(100))
        self.create_imported_collection.side_effect = lambda import_id, parent, name: next(created)
        self.begin_import_batches.side_effect = self._begin
        self.import_batch_done.side_effect = self._batch_done
        return self

    def _begin(self, import_id, expected, plan):
        self.expected, self.done, self.results = list(expected), [], {"_plan": plan}

    def _batch_done(self, import_id, key, result):
        was_complete = set(self.expected) <= set(self.done)
        if key not in self.done:
            self.done.append(key)
            self.results[key] = result
        complete = set(self.expected) <= set(self.done)
        completed_now = complete and not was_complete
        summary = None
        if completed_now:
            plan = self.results["_plan"]
            summary = {
                "collections_created": plan["collections_created"],
                "documents_created": sum(self.results[k]["documents_created"] for k in self.expected),
                "skipped": [*plan["skipped"], *(item for k in self.expected for item in self.results[k]["skipped"])],
            }
        return {
            "status": self.status,
            "done": len(self.done),
            "expected": len(self.expected),
            "completed_now": completed_now,
            "summary": summary,
        }


class TestImportTask:
    def _run(self, monkeypatch, archive_bytes: bytes, add_document=None, batch_files: int | None = None):
        """The import, with the batches it starts run one after the other as a queue would."""
        backend, storage = _FakeBackend().start(), _FakeStorage(archive_bytes)
        backend.add_imported_document.side_effect = add_document or (lambda *args: f"doc-{args[2]}")
        monkeypatch.setattr(tasks._shared, "backend_client", backend)
        monkeypatch.setattr(tasks._shared, "storage", storage)
        monkeypatch.setattr(task_logging, "backend_client", MagicMock())
        if batch_files is not None:
            monkeypatch.setattr(settings, "IMPORT_BATCH_FILES", batch_files)
        waiting = []
        monkeypatch.setattr(tasks.import_zip_batch, "apply_async", lambda args: waiting.append(args[0]))
        backend.waiting = waiting
        tasks.import_zip("import-1")
        backend.started = []
        while waiting:
            payload = waiting.pop(0)
            backend.started.append(payload["batch"])
            tasks.import_zip_batch(payload)
        return backend, storage

    def test_recreates_the_tree_and_reports_a_summary(self, monkeypatch):
        archive = _zip({"a/b/doc.pdf": b"%PDF b", "a/c.md": b"# c", "racine.txt": b"root", "a/run.exe": b"MZ"})

        backend, storage = self._run(monkeypatch, archive)

        backend.create_imported_collection.assert_any_call("import-1", "root", "a")
        backend.create_imported_collection.assert_any_call("import-1", "col-0", "b")
        placed = {call.args[1:3] for call in backend.add_imported_document.call_args_list}
        assert placed == {("col-1", "doc.pdf"), ("col-0", "c.md"), ("root", "racine.txt")}
        for call in backend.add_imported_document.call_args_list:
            assert call.args[3].startswith(f"documents/{call.args[1]}/")
        status, summary = backend.finish_collection_import.call_args.args[1:3]
        assert status == "completed"
        assert summary["collections_created"] == 2 and summary["documents_created"] == 3
        assert summary["skipped"] == [{"path": "a/run.exe", "reason": "type de fichier non pris en charge"}]

    def test_a_small_archive_is_read_by_the_task_itself_in_one_batch(self, monkeypatch):
        backend, _ = self._run(monkeypatch, _zip({"a.pdf": b"%PDF a", "b.pdf": b"%PDF b"}))

        assert backend.started == []
        assert backend.begin_import_batches.call_args.args[1] == ["batch:0"]
        assert backend.finish_collection_import.call_count == 1

    def test_a_big_archive_is_read_by_batches_a_window_of_them_at_a_time(self, monkeypatch):
        monkeypatch.setattr(settings, "IMPORT_WINDOW", 2)
        archive = _zip({f"d{n % 3}/f{n}.pdf": f"%PDF {n}".encode() for n in range(11)})

        backend, storage = self._run(monkeypatch, archive, batch_files=2)

        assert backend.begin_import_batches.call_args.args[1] == [f"batch:{n}" for n in range(6)]
        # The planner starts the window (0 and 1), and each batch that ends starts the one after its
        # window: 0 starts 2, 1 starts 3, 2 starts 4, 3 starts 5.
        assert backend.started == [0, 1, 2, 3, 4, 5]
        assert backend.finish_collection_import.call_count == 1
        status, summary = backend.finish_collection_import.call_args.args[1:3]
        assert status == "completed" and summary["documents_created"] == 11 and summary["collections_created"] == 3
        assert len(storage.uploaded) == 11
        # The plan is stored beside the archive, for the batches to read their files from.
        assert "imports/i.zip.plan.json" in storage.objects

    def test_only_the_window_is_started_by_the_planner(self, monkeypatch):
        monkeypatch.setattr(settings, "IMPORT_WINDOW", 3)
        archive = _zip({f"f{n}.pdf": f"%PDF {n}".encode() for n in range(10)})
        backend, storage = _FakeBackend().start(), _FakeStorage(archive)
        monkeypatch.setattr(tasks._shared, "backend_client", backend)
        monkeypatch.setattr(tasks._shared, "storage", storage)
        monkeypatch.setattr(task_logging, "backend_client", MagicMock())
        monkeypatch.setattr(settings, "IMPORT_BATCH_FILES", 2)
        started = []
        monkeypatch.setattr(tasks.import_zip_batch, "apply_async", lambda args: started.append(args[0]["batch"]))

        tasks.import_zip("import-1")

        assert started == [0, 1, 2]
        backend.finish_collection_import.assert_not_called()

    def test_a_corrupted_archive_fails_cleanly(self, monkeypatch):
        backend, _ = self._run(monkeypatch, b"not a zip at all")

        status, summary, error = backend.finish_collection_import.call_args.args[1:4]
        assert status == "failed" and "corrompue" in error
        backend.create_imported_collection.assert_not_called()

    def test_an_import_past_its_soft_limit_ends_as_failed_with_what_it_created(self, monkeypatch):
        """Never left running (#294): the backend is told, with the summary of the partial import."""
        archive = _zip({"a.pdf": b"%PDF a", "b.pdf": b"%PDF b"})
        added = []

        def add_document(*args):
            added.append(args)
            if len(added) == 1:
                raise SoftTimeLimitExceeded()

        monkeypatch.setattr(settings, "IMPORT_SOFT_TIME_LIMIT_SECONDS", 2 * 3600)
        with pytest.raises(SoftTimeLimitExceeded):
            self._run(monkeypatch, archive, add_document=add_document)

        backend = tasks._shared.backend_client
        status, summary, error = backend.finish_collection_import.call_args.args[1:4]
        assert status == "failed" and "2 h" in error
        assert len(added) == 1

    def test_a_batch_that_fails_ends_the_import_as_failed_and_starts_no_more(self, monkeypatch):
        archive = _zip({f"f{n}.pdf": f"%PDF {n}".encode() for n in range(8)})

        def add_document(*args):
            if args[2] == "f2.pdf":
                raise RuntimeError("backend down")
            return "doc"

        with pytest.raises(RuntimeError):
            self._run(monkeypatch, archive, add_document=add_document, batch_files=2)

        backend = tasks._shared.backend_client
        status, summary, error = backend.finish_collection_import.call_args.args[1:4]
        # What this batch had done before failing - f2, the first it read, raised: nothing - is sent; what
        # the other batches reported is already at the backend.
        assert status == "failed" and "erreur inattendue" in error
        assert summary == {"documents_created": 0, "skipped": []}

    def test_a_batch_of_an_import_that_failed_meanwhile_starts_nothing(self, monkeypatch):
        archive = _zip({f"f{n}.pdf": f"%PDF {n}".encode() for n in range(6)})
        monkeypatch.setattr(settings, "IMPORT_WINDOW", 1)
        backend, storage = _FakeBackend().start(), _FakeStorage(archive)
        backend.add_imported_document.side_effect = lambda *args: "doc"
        monkeypatch.setattr(tasks._shared, "backend_client", backend)
        monkeypatch.setattr(tasks._shared, "storage", storage)
        monkeypatch.setattr(task_logging, "backend_client", MagicMock())
        monkeypatch.setattr(settings, "IMPORT_BATCH_FILES", 2)
        waiting = []
        monkeypatch.setattr(tasks.import_zip_batch, "apply_async", lambda args: waiting.append(args[0]))
        tasks.import_zip("import-1")
        assert [payload["batch"] for payload in waiting] == [0]
        backend.status = "failed"

        tasks.import_zip_batch(waiting.pop())

        assert waiting == []

    def test_an_import_is_not_killed_for_being_long(self):
        assert tasks.import_zip.time_limit is None
        assert tasks.import_zip.soft_time_limit == settings.IMPORT_SOFT_TIME_LIMIT_SECONDS
        assert tasks.import_zip_batch.time_limit is None
        assert tasks.import_zip_batch.soft_time_limit == settings.IMPORT_SOFT_TIME_LIMIT_SECONDS

    def test_each_file_is_registered_with_the_hash_of_its_bytes(self, monkeypatch):
        archive = _zip({"a.pdf": b"%PDF a", "dir/b.md": b"# b"})

        backend, _ = self._run(monkeypatch, archive)

        hashes = {call.args[2]: call.args[4] for call in backend.add_imported_document.call_args_list}
        assert hashes == {
            "a.pdf": hashlib.sha256(b"%PDF a").hexdigest(),
            "b.md": hashlib.sha256(b"# b").hexdigest(),
        }

    def test_a_file_already_in_the_collection_is_neither_stored_nor_registered(self, monkeypatch):
        """Asked by hash before the upload (#300), so a duplicate costs neither storage nor processing."""
        archive = _zip({"new.pdf": b"%PDF new", "copy.pdf": b"%PDF already there"})
        already = hashlib.sha256(b"%PDF already there").hexdigest()
        original = _FakeBackend.start

        def start(self, root="root"):
            original(self, root)
            self.is_imported_duplicate.side_effect = lambda import_id, collection_id, content_hash: (
                content_hash == already
            )
            return self

        monkeypatch.setattr(_FakeBackend, "start", start)

        backend, storage = self._run(monkeypatch, archive)

        assert [call.args[2] for call in backend.add_imported_document.call_args_list] == ["new.pdf"]
        assert storage.upload_fileobj.call_count == 1
        summary = backend.finish_collection_import.call_args.args[2]
        assert summary["documents_created"] == 1
        assert summary["skipped"] == [{"path": "copy.pdf", "reason": "déjà présent dans la collection (doublon)"}]

    def test_a_file_registered_meanwhile_by_another_batch_is_skipped_as_a_duplicate(self, monkeypatch):
        """The backend answers None when it dropped the stored copy: the same file, read by two batches."""
        archive = _zip({"a.pdf": b"%PDF a", "b.pdf": b"%PDF b"})

        backend, _ = self._run(monkeypatch, archive, add_document=lambda *args: None if args[2] == "b.pdf" else "doc")

        summary = backend.finish_collection_import.call_args.args[2]
        assert summary["documents_created"] == 1
        assert summary["skipped"] == [{"path": "b.pdf", "reason": "déjà présent dans la collection (doublon)"}]

    def test_a_refused_archive_creates_nothing(self, monkeypatch):
        monkeypatch.setattr(settings, "ZIP_IMPORT_MAX_FILES", 1)

        backend, _ = self._run(monkeypatch, _zip({"a.pdf": b"%PDF", "b.pdf": b"%PDF"}))

        assert backend.finish_collection_import.call_args.args[1] == "failed"
        backend.add_imported_document.assert_not_called()

    def test_files_are_streamed_to_storage_and_never_stored_when_skipped(self, monkeypatch):
        monkeypatch.setattr(settings, "ZIP_IMPORT_MAX_FILE_BYTES", 1000)
        archive = _zip({"small.pdf": b"%PDF small", "big.pdf": b"%PDF" + b"x" * 5000})

        backend, storage = self._run(monkeypatch, archive)

        # Streamed with upload_fileobj, whole and from its start - never put_object with bytes in memory.
        assert list(storage.uploaded.values()) == [b"%PDF small"]
        assert all(call.args[0].endswith(".plan.json") for call in storage.put_object.call_args_list)
        summary = backend.finish_collection_import.call_args.args[2]
        assert summary["documents_created"] == 1
        assert summary["skipped"][0]["path"] == "big.pdf"

    def test_without_limits_a_large_file_is_imported_whole(self, monkeypatch):
        content = b"%PDF" + os.urandom(5_000_000)  # incompressible: well within the ratio

        backend, storage = self._run(monkeypatch, _zip({"big.pdf": content}))

        assert list(storage.uploaded.values()) == [content]
        assert backend.finish_collection_import.call_args.args[2]["skipped"] == []

    def test_the_archive_is_read_by_ranges_never_downloaded(self, monkeypatch):
        backend, storage = _FakeBackend().start(), _FakeStorage(_zip({"a.pdf": b"%PDF a"}))
        storage.download_fileobj = MagicMock()
        backend.add_imported_document.side_effect = lambda *args: "doc"
        monkeypatch.setattr(tasks._shared, "backend_client", backend)
        monkeypatch.setattr(tasks._shared, "storage", storage)
        monkeypatch.setattr(task_logging, "backend_client", MagicMock())

        tasks.import_zip("import-1")

        storage.download_fileobj.assert_not_called()

    def test_an_archive_announcing_too_many_entries_is_refused_before_its_directory_is_read(self, monkeypatch):
        monkeypatch.setattr(settings, "ZIP_IMPORT_MAX_FILES", 1)  # so at most 10 entries
        archive = _zip({f"f{i}.pdf": b"%PDF" for i in range(11)})
        read_directories = []
        real_zipfile = zipfile.ZipFile
        monkeypatch.setattr(
            importlib.import_module("app.tasks.import_zip").zipfile,
            "ZipFile",
            lambda *args, **kwargs: read_directories.append(1) or real_zipfile(*args, **kwargs),
        )

        backend, _ = self._run(monkeypatch, archive)

        status, _summary, error = backend.finish_collection_import.call_args.args[1:4]
        assert status == "failed" and "11 entrées" in error
        assert read_directories == []
        backend.create_imported_collection.assert_not_called()


class TestRangeReader:
    def _reader(self, data: bytes, block: int = 7):
        calls = []

        class Client:
            def get_object(self, Bucket, Key, Range):  # noqa: N803 - boto3's own names
                start, end = Range.removeprefix("bytes=").split("-")
                calls.append((int(start), int(end)))
                return {"Body": io.BytesIO(data[int(start) : int(end) + 1])}

        return RangeReader(Client(), "bucket", "key", len(data), block_bytes=block), calls

    def test_reads_what_a_file_would_whatever_the_block_size(self):
        data = bytes(range(100))
        reader, _ = self._reader(data)

        reader.seek(30)
        assert reader.read(25) == data[30:55]
        reader.seek(-10, io.SEEK_END)
        assert reader.read() == data[90:]
        reader.seek(0)
        assert reader.read(1000) == data
        assert reader.tell() == 100

    def test_fetches_by_ranges_and_not_again_what_it_holds(self):
        reader, calls = self._reader(bytes(range(100)), block=20)

        reader.seek(10)
        reader.read(5)
        reader.read(4)

        assert calls == [(10, 29)]

    def test_zipfile_reads_an_archive_through_it(self):
        content = os.urandom(50_000)
        archive = _zip({"a/b.pdf": content, "c.txt": b"hello"})
        reader, calls = self._reader(archive, block=4096)

        with zipfile.ZipFile(reader) as zipped:
            assert zipped.read("a/b.pdf") == content
            assert zipped.read("c.txt") == b"hello"
        assert all(end - start < 4096 for start, end in calls)


class TestCountEntries:
    def test_reads_the_announced_count_without_parsing_the_directory(self):
        buffer = io.BytesIO(_zip({"a/b.pdf": b"x", "c.md": b"y", "d.txt": b"z"}))

        assert count_entries(buffer) == 3
        assert buffer.tell() == 0

    def test_not_a_zip_has_no_count(self):
        assert count_entries(io.BytesIO(b"not a zip")) is None


class TestLyingHeaders:
    def test_a_member_cannot_expand_past_the_size_its_header_declares(self):
        # A highly compressible member whose header then claims a tiny expanded size: zipfile stops
        # at the declared size and the CRC fails, so it is skipped as corrupted - it can never expand
        # to more than it declares. That is why plan_import's checks on the declared sizes (per-file,
        # total, compression ratio) hold even against a crafted archive.
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as writer:
            writer.writestr("doc.pdf", b"\0" * 200_000)
        archive = zipfile.ZipFile(io.BytesIO(buffer.getvalue()))
        info = archive.getinfo("doc.pdf")
        info.file_size = info.compress_size  # what a crafted header would claim
        sink = io.BytesIO()

        with pytest.raises(MemberSkippedError, match="corrompu"):
            extract_member(archive, info, cap=10_000_000, sink=sink)
        assert len(sink.getvalue()) <= info.compress_size
