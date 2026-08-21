from __future__ import annotations

import platform
import subprocess
import threading
import time
from collections.abc import Iterator


class WebcamService:
    """Capture USB/UVC video on the ChurchBoard host for network viewers."""

    def __init__(self) -> None:
        self._captures: dict[int, object] = {}
        self._locks: dict[int, threading.Lock] = {}
        self._guard = threading.Lock()

    @staticmethod
    def _cv2():
        try:
            import cv2  # type: ignore
        except ImportError as exc:
            raise RuntimeError("USB camera capture is not included in this installation") from exc
        return cv2

    @staticmethod
    def _mac_names() -> list[str]:
        if platform.system() != "Darwin":
            return []
        try:
            result = subprocess.run(
                ["/usr/sbin/system_profiler", "SPCameraDataType"],
                capture_output=True, text=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        names: list[str] = []
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped.endswith(":") or stripped.startswith(("Camera:", "Model ID:", "Unique ID:")):
                continue
            indent = len(line) - len(line.lstrip())
            if indent >= 8:
                names.append(stripped[:-1])
        return names

    def devices(self) -> list[dict[str, object]]:
        cv2 = self._cv2()
        names = self._mac_names()
        items: list[dict[str, object]] = []
        backend = cv2.CAP_AVFOUNDATION if platform.system() == "Darwin" else cv2.CAP_ANY
        for index in range(max(8, len(names))):
            capture = cv2.VideoCapture(index, backend)
            available = bool(capture.isOpened())
            capture.release()
            if available:
                label = names[len(items)] if len(items) < len(names) else f"USB camera {index + 1}"
                items.append({"id": str(index), "index": index, "label": label})
        return items

    def _capture(self, index: int):
        cv2 = self._cv2()
        with self._guard:
            capture = self._captures.get(index)
            if capture is not None and capture.isOpened():
                return capture
            backend = cv2.CAP_AVFOUNDATION if platform.system() == "Darwin" else cv2.CAP_ANY
            capture = cv2.VideoCapture(index, backend)
            if not capture.isOpened():
                capture.release()
                raise RuntimeError("The selected USB camera is not connected or is busy")
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._captures[index] = capture
            self._locks[index] = threading.Lock()
            return capture

    def frames(self, index: int) -> Iterator[bytes]:
        cv2 = self._cv2()
        while True:
            try:
                capture = self._capture(index)
                with self._locks[index]:
                    ok, frame = capture.read()
                if not ok:
                    self.release(index)
                    time.sleep(0.25)
                    continue
                encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
                if encoded:
                    payload = jpeg.tobytes()
                    yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload + b"\r\n"
            except GeneratorExit:
                return
            except Exception:
                time.sleep(0.5)

    def release(self, index: int) -> None:
        with self._guard:
            capture = self._captures.pop(index, None)
            self._locks.pop(index, None)
        if capture is not None:
            capture.release()

    def close(self) -> None:
        with self._guard:
            indexes = list(self._captures)
        for index in indexes:
            self.release(index)
