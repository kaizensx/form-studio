"""Encode a folder of PNG frames as an H.264 MP4 with Qt Multimedia (no ffmpeg needed).

    python scripts/media/encode_mp4.py FRAMES_DIR OUT.mp4 --fps 30 --width 1440 [--quality High]

Frames are pushed into QMediaRecorder through QVideoFrameInput, which encodes with the FFmpeg that PySide6 ships
(H.264, constant quality). Frames are handed over at the clip's own
frame rate, as a camera would deliver them; pushed faster, the encoder drops all but the first few.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("frames")
    ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--quality", default="High", choices=["VeryLow", "Low", "Normal", "High", "VeryHigh"])
    a = ap.parse_args()

    from PySide6.QtCore import QSize, Qt, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication, QImage
    from PySide6.QtMultimedia import (QMediaCaptureSession, QMediaFormat, QMediaRecorder, QVideoFrame,
                                      QVideoFrameInput)

    app = QGuiApplication(sys.argv[:1])
    files = sorted(Path(a.frames).glob("*.png"))
    if not files:
        print("no frames", file=sys.stderr)
        return 1
    first = QImage(str(files[0]))
    w = a.width - a.width % 2
    h = round(first.height() * w / first.width())
    h -= h % 2
    out = Path(a.out).resolve()
    out.unlink(missing_ok=True)

    session = QMediaCaptureSession()
    vin = QVideoFrameInput()
    session.setVideoFrameInput(vin)
    rec = QMediaRecorder()
    session.setRecorder(rec)
    fmt = QMediaFormat()
    fmt.setFileFormat(QMediaFormat.FileFormat.MPEG4)
    fmt.setVideoCodec(QMediaFormat.VideoCodec.H264)
    rec.setMediaFormat(fmt)
    rec.setVideoResolution(QSize(w, h))
    rec.setVideoFrameRate(a.fps)
    rec.setEncodingMode(QMediaRecorder.EncodingMode.ConstantQualityEncoding)
    rec.setQuality(getattr(QMediaRecorder.Quality, a.quality + "Quality"))
    rec.setOutputLocation(QUrl.fromLocalFile(str(out)))

    state = {"i": 0, "rc": 0, "frame": None, "stopping": False}

    def push():
        if state["i"] < len(files):
            if state["frame"] is None:
                img = QImage(str(files[state["i"]])).convertToFormat(QImage.Format.Format_RGBA8888)
                if img.width() != w or img.height() != h:
                    img = img.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                f = QVideoFrame(img)
                f.setStreamFrameRate(a.fps)          # timestamps follow from the frame rate, not the wall clock
                state["frame"] = f
            if not vin.sendVideoFrame(state["frame"]):
                return                      # the encoder's queue is full: the timer tries again
            state["frame"] = None
            state["i"] += 1
            return
        if not state["stopping"]:
            state["stopping"] = True
            pump.stop()
            state["t"] = 0
            wait.start()                    # stop only once the encoder has written every frame

    def finish_when_written():
        state["t"] += 1
        if rec.duration() >= int((len(files) - 1) * 1000 / a.fps) or state["t"] > 100:
            wait.stop()
            rec.stop()

    wait = QTimer()
    wait.setInterval(50)
    wait.timeout.connect(finish_when_written)

    pump = QTimer()
    pump.setInterval(int(1000 / a.fps))
    pump.timeout.connect(push)

    def on_state(s):
        if s == QMediaRecorder.RecorderState.StoppedState and state["i"] >= len(files):
            QTimer.singleShot(200, app.quit)

    def on_error(err, msg):
        print("recorder error:", err, msg, file=sys.stderr)
        state["rc"] = 1
        app.quit()

    rec.recorderStateChanged.connect(on_state)
    rec.errorOccurred.connect(on_error)
    rec.record()
    pump.start()
    QTimer.singleShot(600_000, app.quit)
    app.exec()
    if not out.exists() or out.stat().st_size == 0:
        print("nothing written", file=sys.stderr)
        return 1
    print(f"{out.name}: {len(files)} frames, {w}x{h}, {out.stat().st_size // 1024} KB")
    return state["rc"]


if __name__ == "__main__":
    sys.exit(main())
