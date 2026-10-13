from __future__ import annotations

import asyncio
import logging
import tempfile
from functools import lru_cache
from pathlib import Path

import httpx

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel, Field

from app.services.interaction_service import (
    interaction_service,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/interaction",
    tags=["Interaction"],
)

MAX_AUDIO_BYTES = 12 * 1024 * 1024

SUPPORTED_AUDIO_TYPES = {
    "audio/webm": ".webm",
    "audio/mp4": ".mp4",
}

transcription_lock = asyncio.Lock()


class AskRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=1000,
    )
    speak: bool = False


class AskResponse(BaseModel):
    question: str
    answer: str
    model: str
    speech_accepted: bool
    speech_error: str | None = None


class TranscriptionResponse(BaseModel):
    text: str


@router.post(
    "/ask",
    response_model=AskResponse,
)
async def ask_g1(request: AskRequest):
    try:
        return await interaction_service.ask(
            question=request.question,
            speak=request.speak,
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except (httpx.HTTPError, RuntimeError) as error:
        logger.exception(
            "Local AI interaction failed"
        )

        raise HTTPException(
            status_code=503,
            detail="Local AI assistant is unavailable",
        ) from error


@lru_cache(maxsize=1)
def get_whisper_model():
    from faster_whisper import WhisperModel

    logger.info(
        "Loading local Whisper model"
    )

    return WhisperModel(
        "tiny.en",
        device="cpu",
        compute_type="int8",
    )


def transcribe_file(audio_path: Path) -> str:
    model = get_whisper_model()

    segments, _ = model.transcribe(
        str(audio_path),
        language="en",
        beam_size=1,
        condition_on_previous_text=False,
    )

    return " ".join(
        segment.text.strip()
        for segment in segments
        if segment.text.strip()
    ).strip()


@router.post(
    "/transcribe",
    response_model=TranscriptionResponse,
)
async def transcribe_audio(
    file: UploadFile = File(...),
):
    content_type = (
        (file.content_type or "")
        .split(";")[0]
        .strip()
        .lower()
    )

    suffix = SUPPORTED_AUDIO_TYPES.get(
        content_type
    )

    if suffix is None:
        raise HTTPException(
            status_code=415,
            detail=(
                "Unsupported audio format. "
                "Please use WebM or MP4."
            ),
        )

    total_size = 0

    try:
        with tempfile.TemporaryDirectory(
            prefix="g1_whisper_"
        ) as temp_directory:
            audio_path = (
                Path(temp_directory)
                / f"visitor_recording{suffix}"
            )

            with audio_path.open("wb") as output:
                while True:
                    chunk = await file.read(
                        1024 * 1024
                    )

                    if not chunk:
                        break

                    total_size += len(chunk)

                    if total_size > MAX_AUDIO_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                "Audio exceeds the "
                                "12 MB limit"
                            ),
                        )

                    output.write(chunk)

            if total_size == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Audio recording is empty",
                )

            try:
                async with transcription_lock:
                    text = await asyncio.to_thread(
                        transcribe_file,
                        audio_path,
                    )

            except Exception as error:
                logger.exception(
                    "Whisper transcription failed"
                )

                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Local Whisper transcription "
                        "is unavailable"
                    ),
                ) from error

            if not text:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "No recognizable speech "
                        "was detected"
                    ),
                )

            return TranscriptionResponse(
                text=text[:1000]
            )

    finally:
        await file.close()