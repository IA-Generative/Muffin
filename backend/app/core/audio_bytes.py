"""What an audio file really is, from its first bytes - not from what the sender called it (#517).

Nothing here decodes audio: decoding a file sent by a person is an attack surface, and it is the engine's to do (the
hub, a service, a pod without secrets). The backend only checks that the bytes begin as one of the container formats a
browser records, and that the type announced is the type found."""

import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class AudioInfo:
    # The family of the container: `webm`, `ogg`, `mp4`, `wav`, `mp3`, `flac`.
    kind: str
    content_type: str
    extension: str


_FORMATS = {
    "webm": AudioInfo("webm", "audio/webm", "webm"),
    "ogg": AudioInfo("ogg", "audio/ogg", "ogg"),
    "mp4": AudioInfo("mp4", "audio/mp4", "m4a"),
    "wav": AudioInfo("wav", "audio/wav", "wav"),
    "mp3": AudioInfo("mp3", "audio/mpeg", "mp3"),
    "flac": AudioInfo("flac", "audio/flac", "flac"),
}

# The types a sender may announce for each family: what a browser says, and the usual spellings.
_ANNOUNCED = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "application/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/x-m4a": "mp4",
    "audio/m4a": "mp4",
    "audio/aac": "mp4",
    "video/mp4": "mp4",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/vnd.wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
}


class NotAudioError(ValueError):
    """The bytes are none of the formats that are taken."""


def sniff(data: bytes) -> AudioInfo:
    """The format of these bytes, or `NotAudioError`."""
    head = data[:16]
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return _FORMATS["webm"]
    if head[:4] == b"OggS":
        return _FORMATS["ogg"]
    if head[4:8] == b"ftyp":
        return _FORMATS["mp4"]
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return _FORMATS["wav"]
    if head[:4] == b"fLaC":
        return _FORMATS["flac"]
    # An MP3 begins with an ID3 tag, or straight with a frame: eleven bits at one.
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return _FORMATS["mp3"]
    raise NotAudioError("not a known audio container")


def family_of(announced: str | None) -> str | None:
    """The family a type announced belongs to (`audio/webm;codecs=opus` -> `webm`), None if it is no audio type."""
    base = (announced or "").split(";")[0].strip().lower()
    return _ANNOUNCED.get(base)


def wav_seconds(data: bytes) -> float | None:
    """The length of a WAV file, read from its header (the one format whose length is cheap and certain to know), or
    None when the header does not say."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    byte_rate = data_size = None
    offset = 12
    while offset + 8 <= len(data):
        chunk, size = data[offset : offset + 4], struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        if chunk == b"fmt " and offset + 20 <= len(data):
            byte_rate = struct.unpack("<I", data[offset + 16 : offset + 20])[0]
        elif chunk == b"data":
            data_size = min(size, len(data) - offset - 8)
            break
        offset += 8 + size + (size & 1)
    if not byte_rate or data_size is None:
        return None
    return data_size / byte_rate
