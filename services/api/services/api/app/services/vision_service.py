from __future__ import annotations

import threading
from typing import Any

import cv2
import numpy as np
from ultralytics import YOLO


class VisionService:
    def __init__(self) -> None:
        self._model: YOLO | None = None
        self._lock = threading.Lock()
        self.model_name = "yolo11n.pt"

    def _get_model(self) -> YOLO:
        if self._model is None:
            self._model = YOLO(self.model_name)
        return self._model

    def detect(
        self,
        image_bytes: bytes,
        confidence: float = 0.25,
    ) -> dict[str, Any]:
        array = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)

        if image is None:
            raise ValueError("Invalid or unsupported image")

        height, width = image.shape[:2]

        # Protect shared model initialization and inference.
        with self._lock:
            model = self._get_model()

            results = model.predict(
                source=image,
                conf=confidence,
                imgsz=640,
                verbose=False,
                device="cpu",
            )

        detections: list[dict[str, Any]] = []

        for result in results:
            if result.boxes is None:
                continue

            for box in result.boxes:
                class_id = int(box.cls[0].item())
                score = float(box.conf[0].item())
                x1, y1, x2, y2 = box.xyxy[0].tolist()

                detections.append(
                    {
                        "label": str(result.names[class_id]),
                        "class_id": class_id,
                        "confidence": round(score, 4),
                        "bbox": {
                            "x1": round(x1, 2),
                            "y1": round(y1, 2),
                            "x2": round(x2, 2),
                            "y2": round(y2, 2),
                        },
                    }
                )

        return {
            "status": "success",
            "model": self.model_name,
            "image": {
                "width": width,
                "height": height,
            },
            "count": len(detections),
            "detections": detections,
        }


vision_service = VisionService()