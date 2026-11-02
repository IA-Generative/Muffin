from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.voice import (
    SpeechIn,
    TranscriptionOut,
    VoiceSettingsOut,
    VoiceSettingsUpdate,
    VoiceStatusOut,
    VoiceTestOut,
)
from app.services import voice_service
from app.services.app_settings_service import NotAdminError
from app.services.voice_service import VoiceError, VoiceService

router = APIRouter(tags=["Voice"])


def get_voice_service(db: Annotated[AsyncSession, Depends(get_db)]) -> VoiceService:
    return VoiceService(db)


ServiceDep = Annotated[VoiceService, Depends(get_voice_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


def _refused(error: VoiceError) -> HTTPException:
    """The API's error: the status, and a code that does not change with words for the person."""
    return HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message})


def _not_admin() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


@router.get(
    "/voice/status",
    summary="Whether the page records and reads through the server, or leaves it to the browser, and the limits",
    response_model=VoiceStatusOut,
)
async def get_status(user: UserDep, service: ServiceDep) -> VoiceStatusOut:
    return await service.status(user)


@router.post(
    "/transcriptions",
    summary="Turn a recording into text. The audio goes to the engine and is dropped: nothing is kept. 404 when the "
    "function is off; the engine is not called before the recording is checked",
    response_model=TranscriptionOut,
)
async def transcribe(
    user: UserDep,
    service: ServiceDep,
    file: Annotated[UploadFile, File(description="The recording")],
    language: Annotated[str | None, Form()] = None,
    duration_seconds: Annotated[float | None, Form(ge=0, le=86400)] = None,
) -> TranscriptionOut:
    # Never more than the installation's own limit is read into memory: the administrator's setting can only be lower.
    data = await file.read(voice_service._settings.VOICE_STT_MAX_BYTES_LIMIT + 1)
    try:
        return await service.transcribe(user, data, file.content_type, language, duration_seconds)
    except VoiceError as error:
        raise _refused(error) from error


@router.post(
    "/speech",
    summary="Read a text aloud: the audio of it. Nothing is kept. 404 when the function is off",
    response_class=Response,
    responses={200: {"content": {"audio/mpeg": {}, "audio/wav": {}, "audio/flac": {}, "audio/ogg": {}}}},
)
async def speak(body: SpeechIn, user: UserDep, service: ServiceDep) -> Response:
    try:
        audio, content_type = await service.speak(user, body.text, body.language)
    except VoiceError as error:
        raise _refused(error) from error
    return Response(content=audio, media_type=content_type, headers={"Cache-Control": "no-store"})


@router.get("/admin/voice", summary="The settings of the voice (administrators)", response_model=VoiceSettingsOut)
async def get_settings(user: UserDep, service: ServiceDep) -> VoiceSettingsOut:
    try:
        return await service.get_settings(user)
    except NotAdminError as error:
        raise _not_admin() from error


@router.patch(
    "/admin/voice", summary="Change the settings of the voice (administrators)", response_model=VoiceSettingsOut
)
async def update_settings(body: VoiceSettingsUpdate, user: UserDep, service: ServiceDep) -> VoiceSettingsOut:
    try:
        return await service.update_settings(user, body)
    except NotAdminError as error:
        raise _not_admin() from error
    except VoiceError as error:
        raise _refused(error) from error


@router.post(
    "/admin/voice/test-transcription",
    summary="Send a second of silence to the transcription engine and say what came back (administrators)",
    response_model=VoiceTestOut,
)
async def test_transcription(user: UserDep, service: ServiceDep) -> VoiceTestOut:
    try:
        return await service.test_transcription(user)
    except NotAdminError as error:
        raise _not_admin() from error


@router.post(
    "/admin/voice/test-speech",
    summary="Ask the speech engine for a short sentence and say what came back (administrators)",
    response_model=VoiceTestOut,
)
async def test_speech(user: UserDep, service: ServiceDep) -> VoiceTestOut:
    try:
        return await service.test_speech(user)
    except NotAdminError as error:
        raise _not_admin() from error
