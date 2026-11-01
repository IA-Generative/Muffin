"""What bytes are, when an image is meant (#518): the type is read from the bytes and never taken from what the sender
says, and only a raster image is accepted - PNG, JPEG or WebP - so that nothing the provider (or a server it points to)
sends back is served to a browser as something else, a vector image with a script in it above all.

No library decodes the image: the headers hold what is checked (the type and the size), and nothing here draws it."""

import struct
import zlib
from dataclasses import dataclass

_PNG = b"\x89PNG\r\n\x1a\n"
# The comment written in a PNG: where the image comes from, for whoever opens the file outside of Muffin.
PNG_SOURCE_TEXT = b"Source\x00AI-generated image (Muffin)"


class NotAnImageError(ValueError):
    """The bytes are not a raster image Muffin keeps, or are one that is too large; the message says why in words that
    show nothing of the bytes."""


@dataclass(frozen=True)
class ImageInfo:
    content_type: str
    extension: str
    width: int
    height: int


def inspect(data: bytes, *, max_side: int) -> ImageInfo:
    """The type and the size of a PNG, a JPEG or a WebP - and NotAnImageError for anything else, a truncated header, an
    empty image or one with a side above `max_side`."""
    if data.startswith(_PNG):
        info = _png(data)
    elif data.startswith(b"\xff\xd8\xff"):
        info = _jpeg(data)
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        info = _webp(data)
    else:
        raise NotAnImageError("Le fichier n'est pas une image PNG, JPEG ou WebP.")
    if info.width < 1 or info.height < 1:
        raise NotAnImageError("L'image est vide.")
    if max(info.width, info.height) > max_side:
        raise NotAnImageError("L'image est trop grande.")
    return info


def _png(data: bytes) -> ImageInfo:
    if len(data) < 33 or data[12:16] != b"IHDR":
        raise NotAnImageError("L'image PNG est tronquée.")
    width, height = struct.unpack(">II", data[16:24])
    return ImageInfo("image/png", "png", width, height)


def _jpeg(data: bytes) -> ImageInfo:
    position = 2
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            position += 1
            continue
        marker = data[position + 1]
        if marker == 0xFF:  # fill byte
            position += 1
            continue
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:  # markers with no length
            position += 2
            continue
        if marker == 0xD9:
            break
        length = struct.unpack(">H", data[position + 2 : position + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if position + 9 > len(data):
                break
            height, width = struct.unpack(">HH", data[position + 5 : position + 9])
            return ImageInfo("image/jpeg", "jpg", width, height)
        position += 2 + length
    raise NotAnImageError("L'image JPEG est tronquée.")


def _webp(data: bytes) -> ImageInfo:
    kind = data[12:16]
    chunk = data[20:]
    if kind == b"VP8X" and len(chunk) >= 10:
        width = int.from_bytes(chunk[4:7], "little") + 1
        height = int.from_bytes(chunk[7:10], "little") + 1
    elif kind == b"VP8 " and len(chunk) >= 10 and chunk[3:6] == b"\x9d\x01\x2a":
        width = struct.unpack("<H", chunk[6:8])[0] & 0x3FFF
        height = struct.unpack("<H", chunk[8:10])[0] & 0x3FFF
    elif kind == b"VP8L" and len(chunk) >= 5 and chunk[0] == 0x2F:
        bits = int.from_bytes(chunk[1:5], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
    else:
        raise NotAnImageError("L'image WebP est illisible.")
    return ImageInfo("image/webp", "webp", width, height)


def label_png(data: bytes) -> bytes:
    """The PNG with a `tEXt` chunk saying it is an AI-generated image, put right after its header. The pixels are
    untouched. Other types are returned as they are: the label on the screen is what they have."""
    if not data.startswith(_PNG) or len(data) < 33:
        return data
    chunk = struct.pack(">I", len(PNG_SOURCE_TEXT)) + b"tEXt" + PNG_SOURCE_TEXT
    chunk += struct.pack(">I", zlib.crc32(b"tEXt" + PNG_SOURCE_TEXT))
    return data[:33] + chunk + data[33:]
