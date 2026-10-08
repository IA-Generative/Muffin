"""Pixel size of an image from its header - enough to size an ODT frame without an imaging
library. Only the formats LibreOffice and browsers agree on: PNG, JPEG and GIF."""

import struct


class UnsupportedImageError(ValueError):
    pass


def image_size(data: bytes) -> tuple[int, int, str]:
    """(width, height, extension) of a PNG, JPEG or GIF; raises UnsupportedImageError otherwise."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return width, height, "png"
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return width, height, "gif"
    if data[:2] == b"\xff\xd8":
        return (*_jpeg_size(data), "jpg")
    raise UnsupportedImageError("seuls les formats PNG, JPEG et GIF sont acceptés pour une image")


def _jpeg_size(data: bytes) -> tuple[int, int]:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = struct.unpack(">H", data[index + 2 : index + 4])[0]
        # Start-of-frame markers (except DHT/JPG/DAC) carry the dimensions.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return width, height
        index += 2 + length
    raise UnsupportedImageError("image JPEG illisible")
