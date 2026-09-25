r"""Save a JPG when a person is detected by a webcam or Raspberry Pi camera.

Save this file in your repository's raspberry_pi folder.

WINDOWS / USB WEBCAM -- PowerShell, from the repository root:
    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install "opencv-python>=4.8,<5"
    python raspberry_pi/computer_vision.py

RASPBERRY PI OS -- terminal, from the repository root:
    sudo apt update
    sudo apt install python3-opencv python3-picamera2 python3-venv
    python3 -m venv --system-site-packages .venv
    source .venv/bin/activate
    python raspberry_pi/computer_vision.py --picamera2

For a USB webcam on a Pi, omit --picamera2. Use --headless when there is no
desktop display (for example over SSH). Use --source 1 for a second webcam.
An existing local video file can also be used: --source path/to/video.mp4

Photos go into captures beside this script unless --output is supplied.
Add captures/ to your repository's .gitignore so photos stay out of Git.
The default saves after 3 consecutive positive frames, at least 10 seconds
apart, including while someone remains visible. This is a frame-level gate;
it does not track whether detections across frames belong to the same person.

Press Q in the preview window or Ctrl+C in the terminal to stop.

This basic HOG detector runs locally without downloading a separate model.
It works best on visible, upright bodies. It can miss seated people, close-up
faces, small or partly hidden people, and can produce false detections.
It is a learning project, not a tested security monitoring system.

Validation: Linux replay tested with Python 3.12 and OpenCV 4.14.0. Person
detection, blank-frame handling, cooldown, JPG writing, and write-error
handling passed. A physical camera and Windows preview were not tested.

References:
https://docs.opencv.org/4.x/d5/d33/structcv_1_1HOGDescriptor.html
https://www.raspberrypi.com/documentation/computers/camera_software.html
"""

import argparse
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import sys
import time
from uuid import uuid4


class CaptureGate:
    """Require repeated detections and enough time since the last saved photo."""

    def __init__(self, cooldown=10.0, confirm_frames=3):
        self.cooldown = cooldown
        self.confirm_frames = confirm_frames
        self.streak = 0
        self.last_saved = float("-inf")

    def ready(self, person_found, now):
        self.streak = min(self.streak + 1, self.confirm_frames) if person_found else 0
        return (self.streak >= self.confirm_frames
                and now - self.last_saved >= self.cooldown)

    def mark_saved(self, now):
        self.last_saved = now
        self.streak = 0


def detect_people(cv2, detector, frame):
    """Detect at a reduced size and return rectangles in original coordinates."""
    height, width = frame.shape[:2]
    if width < 64 or height < 128:
        return []
    factor = min(1.0, 640.0 / width)
    small = cv2.resize(frame, (round(width * factor), round(height * factor)))
    if small.shape[0] < 128:
        return []
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    rectangles, _scores = detector.detectMultiScale(
        gray, hitThreshold=0.5, winStride=(8, 8), padding=(8, 8), scale=1.05
    )
    return [tuple(round(int(value) / factor) for value in rectangle)
            for rectangle in rectangles]


def save_snapshot(cv2, frame, output):
    """Save the unmarked camera frame; report failed writes instead of success."""
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%fZ")
    path = output / f"person_{stamp}_{uuid4().hex[:8]}.jpg"
    if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
        raise OSError(f"Could not save photo: {path}")
    return path


def parse_args():
    parser = argparse.ArgumentParser(description="Take photos when a person is detected.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--source", default="0", help="webcam number or local video path")
    source.add_argument("--picamera2", action="store_true", help="use a Pi ribbon-cable camera")
    parser.add_argument("--headless", action="store_true", help="disable the preview window")
    parser.add_argument("--cooldown", type=float, default=10.0, help="minimum seconds between photos")
    parser.add_argument("--confirm-frames", type=int, default=3, help="positive frames needed before saving")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parent / "captures")
    args = parser.parse_args()
    if not math.isfinite(args.cooldown) or args.cooldown <= 0:
        parser.error("--cooldown must be a finite number greater than zero")
    if args.confirm_frames < 1:
        parser.error("--confirm-frames must be at least 1")
    if not args.picamera2 and not args.source.isdecimal():
        args.source = str(Path(args.source).expanduser().resolve())
        if not Path(args.source).is_file():
            parser.error("--source must be a webcam number or an existing local video file")
    if (not args.headless and sys.platform.startswith("linux")
            and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))):
        parser.error("No desktop display found. Add --headless to run without a window.")
    args.output = args.output.expanduser().resolve()
    return args


def run(cv2, args):
    detector = cv2.HOGDescriptor()
    detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    gate = CaptureGate(args.cooldown, args.confirm_frames)
    camera = None
    pi_camera = None
    is_video_file = not args.picamera2 and not args.source.isdecimal()
    saved_count = 0

    try:
        if args.picamera2:
            try:
                from picamera2 import Picamera2
            except ImportError as error:
                raise RuntimeError(
                    "Picamera2 is missing. Follow the Raspberry Pi setup at the top of this file."
                ) from error
            pi_camera = Picamera2()
            # Picamera2 RGB888 produces BGR byte order, as expected by OpenCV.
            config = pi_camera.create_video_configuration(
                main={"size": (640, 480), "format": "RGB888"}
            )
            pi_camera.configure(config)
            pi_camera.start()
            time.sleep(1.0)
        else:
            source = args.source if is_video_file else int(args.source)
            camera = cv2.VideoCapture(source)
            if not camera.isOpened():
                raise RuntimeError(
                    f"Cannot open camera/video {args.source!r}. Close other camera apps, "
                    "check camera permissions, or try --source 1."
                )
            if not is_video_file:
                camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        print(f"Watching for people. Photos: {args.output}", flush=True)
        print(f"Confirmation: {args.confirm_frames} frames | cooldown: {args.cooldown:g} s")
        if is_video_file:
            print("Video input uses processing time for the cooldown, not video timestamps.")
        print("Press Q in the preview or Ctrl+C in the terminal to stop.", flush=True)

        while True:
            if pi_camera is not None:
                frame = pi_camera.capture_array("main")
            else:
                ok, frame = camera.read()
                if not ok:
                    if is_video_file:
                        print("Video ended or a frame could not be decoded.")
                        break
                    raise RuntimeError("Camera stopped returning frames. Check its connection.")
            if frame is None or frame.size == 0:
                raise RuntimeError("Camera returned an empty image.")

            boxes = detect_people(cv2, detector, frame)
            if gate.ready(bool(boxes), time.monotonic()):
                path = save_snapshot(cv2, frame, args.output)
                gate.mark_saved(time.monotonic())
                saved_count += 1
                print(f"Saved: {path}", flush=True)

            if not args.headless:
                preview = frame.copy()
                for x, y, width, height in boxes:
                    cv2.rectangle(preview, (x, y), (x + width, y + height), (0, 255, 0), 2)
