"""What bytes are, when an image is meant (#518): the type comes from the bytes, only a raster image is kept, and the
label put in a PNG leaves the image as it was."""

import struct
import zlib

import pytest

from app.core import image_bytes
from app.core.image_bytes import NotAnImageError, inspect, label_png

MAX_SIDE = 4096


def png(width: int = 3, height: int = 2) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def jpeg(width: int = 5, height: int = 4) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def webp_lossless(width: int = 7, height: int = 6) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    chunk = b"\x2f" + bits.to_bytes(4, "little")
    body = b"WEBP" + b"VP8L" + struct.pack("<I", len(chunk)) + chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


def webp_lossy(width: int = 9, height: int = 8) -> bytes:
    chunk = b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", width, height) + b"\x00" * 4
    body = b"WEBP" + b"VP8 " + struct.pack("<I", len(chunk)) + chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


def webp_extended(width: int = 11, height: int = 10) -> bytes:
    chunk = b"\x00" * 4 + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    body = b"WEBP" + b"VP8X" + struct.pack("<I", len(chunk)) + chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (png(), ("image/png", "png", 3, 2)),
        (jpeg(), ("image/jpeg", "jpg", 5, 4)),
        (webp_lossless(), ("image/webp", "webp", 7, 6)),
        (webp_lossy(), ("image/webp", "webp", 9, 8)),
        (webp_extended(), ("image/webp", "webp", 11, 10)),
    ],
)
def test_the_type_and_the_size_are_read_from_the_bytes(data, expected):
    info = inspect(data, max_side=MAX_SIDE)

    assert (info.content_type, info.extension, info.width, info.height) == expected


@pytest.mark.parametrize(
    "data",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"<!doctype html><script>alert(1)</script>",
        b"GIF89a\x01\x00\x01\x00",
        b"%PDF-1.7",
        b"",
        b"\x89PNG\r\n\x1a\n",  # a signature and nothing else
        b"\xff\xd8\xff",
        b"RIFF\x04\x00\x00\x00WEBP",
    ],
)
def test_what_is_not_a_raster_image_or_is_cut_short_is_refused(data):
    with pytest.raises(NotAnImageError):
        inspect(data, max_side=MAX_SIDE)


def test_a_side_past_the_limit_and_an_empty_image_are_refused():
    with pytest.raises(NotAnImageError, match="trop grande"):
        inspect(png(5000, 10), max_side=MAX_SIDE)
    with pytest.raises(NotAnImageError, match="vide"):
        inspect(png(0, 10), max_side=MAX_SIDE)


def test_the_label_is_a_text_chunk_after_the_header_and_the_rest_of_the_image_is_the_same():
    original = png()

    labelled = label_png(original)

    assert labelled[:33] == original[:33] and labelled[33:].endswith(original[33:])
    assert image_bytes.PNG_SOURCE_TEXT in labelled
    assert inspect(labelled, max_side=MAX_SIDE).width == 3  # still a PNG, the same size
    # The new chunk is well formed: its length, its type and the checksum of both.
    length = struct.unpack(">I", labelled[33:37])[0]
    kind, data = labelled[37:41], labelled[41 : 41 + length]
    assert kind == b"tEXt" and struct.unpack(">I", labelled[41 + length : 45 + length])[0] == zlib.crc32(kind + data)


def test_only_a_png_is_labelled_in_the_file():
    assert label_png(jpeg()) == jpeg() and label_png(b"not an image") == b"not an image"
