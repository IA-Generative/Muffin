"""What a recording is, from its first bytes and not from what the sender called it (#517)."""

import struct

import pytest

from app.core import audio_bytes as a
from app.services.voice_service import silent_wav

WEBM = b"\x1a\x45\xdf\xa3" + bytes(100)
OGG = b"OggS\x00\x02" + bytes(100)
MP4 = b"\x00\x00\x00\x20ftypM4A " + bytes(100)
MP3_TAG = b"ID3\x04\x00" + bytes(100)
MP3_FRAME = b"\xff\xfb\x90\x00" + bytes(100)
FLAC = b"fLaC" + bytes(100)


@pytest.mark.parametrize(
    "data, kind",
    [
        (WEBM, "webm"),
        (OGG, "ogg"),
        (MP4, "mp4"),
        (silent_wav(), "wav"),
        (MP3_TAG, "mp3"),
        (MP3_FRAME, "mp3"),
        (FLAC, "flac"),
    ],
)
def test_each_container_a_browser_records_is_recognised_by_its_first_bytes(data, kind):
    assert a.sniff(data).kind == kind


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"%PDF-1.7\n",
        b"<html><body>Not found</body></html>",
        b"MZ\x90\x00",
        b"\x89PNG\r\n\x1a\n",
        b"GIF89a",
        bytes(64),
    ],
)
def test_what_is_not_audio_is_refused_whatever_it_is_called(data):
    with pytest.raises(a.NotAudioError):
        a.sniff(data)


def test_the_type_announced_is_read_without_its_parameters_and_unknown_ones_belong_to_no_family():
    assert a.family_of("audio/webm;codecs=opus") == "webm"
    assert a.family_of("Audio/MP4") == "mp4"
    assert a.family_of("audio/x-m4a") == "mp4"
    assert a.family_of("video/webm") == "webm"
    assert a.family_of("application/pdf") is None and a.family_of("text/html") is None and a.family_of(None) is None


def test_the_length_of_a_wav_is_read_from_its_header_and_nothing_else_is_guessed():
    assert a.wav_seconds(silent_wav(2.5, rate=8000)) == pytest.approx(2.5)
    assert a.wav_seconds(WEBM) is None
    assert a.wav_seconds(b"RIFF" + bytes(10)) is None


def test_a_wav_header_that_lies_about_its_size_never_reads_past_the_data():
    wav = bytearray(silent_wav(1.0))
    data_at = wav.index(b"data")
    wav[data_at + 4 : data_at + 8] = struct.pack("<I", 2**31)

    assert a.wav_seconds(bytes(wav)) == pytest.approx(1.0)
