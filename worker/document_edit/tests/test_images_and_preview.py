import io
import shutil
import struct
import subprocess
import zipfile
from unittest.mock import MagicMock

import pytest
from odfdo import Document

from app import preview
from app.edit_types import OperationError
from app.image_size import UnsupportedImageError, image_size
from app.odt_editor import ImageData, insert_images
from app.operations import SectionRef
from tests.odt_fixture import PNG, build_odt


def _png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x02\x00\x00\x00"
    )


def _jpeg(width: int, height: int) -> bytes:
    sof = b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", height, width) + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8\xff\xe0\x00\x04ab" + sof + b"\xff\xd9"


def _gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00\x00\x00"


# -- image size ---------------------------------------------------------------------------------


def test_the_size_and_kind_of_a_png_a_jpeg_and_a_gif_are_read_from_their_headers():
    assert image_size(_png(640, 480)) == (640, 480, "png")
    assert image_size(_jpeg(1200, 800)) == (1200, 800, "jpg")
    assert image_size(_gif(32, 16)) == (32, 16, "gif")
    assert image_size(PNG) == (1, 1, "png")


@pytest.mark.parametrize("data", [b"", b"not an image", b"RIFFxxxxWEBPVP8 ", b"%PDF-1.4", b"\xff\xd8\xff"])
def test_anything_else_is_rejected(data):
    with pytest.raises(UnsupportedImageError):
        image_size(data)


# -- inserting images ---------------------------------------------------------------------------


def _images(data: bytes):
    document = Document(io.BytesIO(data))
    return document.body.get_frames()


def test_an_image_goes_in_a_paragraph_of_its_own_at_the_requested_spot_and_keeps_its_extension():
    source = build_odt()
    image = ImageData("img-1", "Plan d'accès", _png(480, 240), SectionRef(heading="Contacts"), 1)

    result = insert_images(source, [image])

    document = Document(io.BytesIO(result.data))
    children = [(c.tag, c.style, c.text_recursive.strip()) for c in document.body.children][-4:]
    assert children[0][2] == "Contacts"
    assert children[1][2] == "RH : rh@example.org"
    # The image paragraph sits right after paragraph 1, with the body style of its neighbours.
    assert children[2][:2] == ("text:p", "Corps")
    assert children[3][2] == "IT : it@example.org"
    assert len(_images(result.data)) == len(_images(source)) + 1
    pictures = [n for n in zipfile.ZipFile(io.BytesIO(result.data)).namelist() if n.endswith(".png")]
    assert len(pictures) == 2  # the fixture's logo and the new one - both with a real extension
    assert result.summary == ["Image « Plan d'accès » insérée après le paragraphe 1 de « Contacts »."]


def test_an_image_with_no_section_goes_at_the_end_of_the_document():
    result = insert_images(build_odt(), [ImageData("img-1", "Logo", PNG)])

    document = Document(io.BytesIO(result.data))
    assert document.body.children[-1].get_frames()
    assert result.summary == ["Image « Logo » insérée à la fin du document."]


def test_an_image_is_sized_from_its_pixels_and_never_wider_than_the_page():
    result = insert_images(
        build_odt(),
        [ImageData("small", "Petite", _png(96, 48)), ImageData("big", "Grande", _png(4000, 2000))],
    )

    frames = {f.name: f for f in _images(result.data) if f.name and f.name.startswith("Image_")}
    small, big = frames["Image_small"], frames["Image_big"]
    assert small.get_attribute("svg:width") == "2.54cm"  # 96 px at 96 dpi
    assert small.get_attribute("svg:height") == "1.27cm"
    assert big.get_attribute("svg:width") == "16.00cm"  # capped to the page body, ratio kept
    assert big.get_attribute("svg:height") == "8.00cm"


def test_two_images_can_be_inserted_in_one_call_and_the_first_one_is_kept():
    result = insert_images(
        build_odt(),
        [
            ImageData("a", "A", PNG, SectionRef(heading="Contacts"), 0),
            ImageData("b", "B", PNG, SectionRef(heading="Étapes")),
        ],
    )
    assert len(result.summary) == 2
    assert len(_images(result.data)) == 3  # the fixture's own logo + the two new ones


@pytest.mark.parametrize(
    ("image", "message"),
    [
        (ImageData("a", "Plan", PNG, SectionRef(heading="Inexistant")), "« Inexistant » introuvable"),
        (ImageData("a", "Plan", PNG, SectionRef(heading="Contacts"), 9), "impossible d'insérer après le 9"),
        (ImageData("a", "Plan", b"not an image"), "image « Plan »"),
    ],
)
def test_an_image_that_cannot_be_placed_fails_the_whole_call(image, message):
    with pytest.raises(OperationError, match=message):
        insert_images(build_odt(), [ImageData("ok", "Bonne", PNG), image])


# -- PDF preview --------------------------------------------------------------------------------


def _fake_soffice(monkeypatch, *, returncode=0, write_pdf=True, stderr=b"", capture=None):
    def run(command, **kwargs):
        if capture is not None:
            capture.update(command=command, **kwargs)
        outdir = command[command.index("--outdir") + 1]
        if write_pdf:
            with open(f"{outdir}/draft.pdf", "wb") as pdf:
                pdf.write(b"%PDF-1.7 fake")
        return subprocess.CompletedProcess(command, returncode, b"", stderr)

    monkeypatch.setattr(preview.subprocess, "run", run)


def test_the_conversion_runs_with_its_own_profile_and_a_timeout_and_returns_the_pdf(monkeypatch):
    seen: dict = {}
    _fake_soffice(monkeypatch, capture=seen)

    assert preview.convert_to_pdf(b"odt") == b"%PDF-1.7 fake"

    command = seen["command"]
    assert command[0] == "soffice"
    assert any(part.startswith("-env:UserInstallation=file://") for part in command)
    assert "--headless" in command and "pdf" in command
    assert seen["timeout"] == preview.settings.PREVIEW_TIMEOUT_SECONDS


def test_two_conversions_never_share_a_profile(monkeypatch):
    profiles = []

    def run(command, **kwargs):
        profiles.append(next(p for p in command if p.startswith("-env:UserInstallation")))
        outdir = command[command.index("--outdir") + 1]
        open(f"{outdir}/draft.pdf", "wb").write(b"%PDF")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(preview.subprocess, "run", run)
    preview.convert_to_pdf(b"a")
    preview.convert_to_pdf(b"b")

    assert profiles[0] != profiles[1]


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"returncode": 1, "stderr": b"boom"}, "a échoué : boom"),
        ({"write_pdf": False}, "a échoué"),
    ],
)
def test_a_failed_conversion_raises_a_readable_error(monkeypatch, options, message):
    _fake_soffice(monkeypatch, **options)

    with pytest.raises(preview.PreviewError, match=message):
        preview.convert_to_pdf(b"odt")


def test_a_timeout_and_a_missing_libreoffice_are_reported(monkeypatch):
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(preview.subprocess, "run", timeout)
    with pytest.raises(preview.PreviewError, match="dépassé"):
        preview.convert_to_pdf(b"odt")

    monkeypatch.setattr(preview.subprocess, "run", MagicMock(side_effect=FileNotFoundError()))
    with pytest.raises(preview.PreviewError, match="introuvable"):
        preview.convert_to_pdf(b"odt")


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed here")
def test_libreoffice_really_renders_an_odt_with_an_inserted_image():
    edited = insert_images(build_odt(), [ImageData("a", "Logo", _png(200, 100))]).data

    pdf = preview.convert_to_pdf(edited)

    assert pdf.startswith(b"%PDF")
