from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.services.vision_service import vision_service


router = APIRouter(
    prefix="/api/vision",
    tags=["Vision"],
)

MAX_IMAGE_BYTES = 10 * 1024 * 1024


@router.get("/status")
async def vision_status():
    return {
        "status": "ready",
        "model": vision_service.model_name,
        "camera_connected": False,
        "camera_source": "test-image",
        "object_detection": "available",
        "note": "G1 WebRTC camera authentication is pending",
    }


@router.post("/detect")
async def detect_objects(
    file: UploadFile = File(...),
):
    if file.content_type not in {
        "image/jpeg",
        "image/png",
        "image/webp",
    }:
        raise HTTPException(
            status_code=415,
            detail="Only JPEG, PNG and WebP images are supported",
        )

    try:
        image_bytes = await file.read(MAX_IMAGE_BYTES + 1)

        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Image exceeds 10 MB limit",
            )

        if not image_bytes:
            raise HTTPException(
                status_code=400,
                detail="Uploaded image is empty",
            )

        return await run_in_threadpool(
            vision_service.detect,
            image_bytes,
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    finally:
        await file.close()