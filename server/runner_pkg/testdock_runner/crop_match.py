"""Match an unregistered snapshot crop in an isolated runner process."""
from __future__ import annotations

import base64
import json
import sys


def match_crop(source: bytes, current: bytes, region: list[int], threshold: float) -> dict:
    import cv2
    import numpy as np
    from mobile_auto.imaging.engine import (
        capture_center_from_region,
        decode_rgb,
        match_template,
    )

    frame = decode_rgb(source, what="source snapshot")
    height, width = frame.shape[:2]
    x, y, w, h = region
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise ValueError("裁剪区域超出快照")
    crop = np.ascontiguousarray(frame[y:y+h, x:x+w, ::-1])
    ok, encoded = cv2.imencode(".png", crop)
    if not ok:
        raise ValueError("模板编码失败")
    found = match_template(
        current, encoded.tobytes(), confidence=threshold,
        source_resolution=(width, height),
        capture_center=capture_center_from_region(region, (width, height)),
    )
    return {
        "count": len(found),
        "matches": [{"x": r.x, "y": r.y, "width": r.width, "height": r.height} for r in found],
        "scores": [round(r.confidence, 6) for r in found],
    }


if __name__ == "__main__":
    from .env import ensure_vendor_on_path
    ensure_vendor_on_path()
    body = json.load(sys.stdin)
    try:
        result = match_crop(base64.b64decode(body["source"]), base64.b64decode(body["current"]),
                            body["region"], body["threshold"])
    except Exception as exc:
        result = {"error": str(exc)}
    print(json.dumps(result))
