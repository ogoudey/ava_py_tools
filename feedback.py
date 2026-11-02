"""Feedback service: pulls from the base API on loop threads, serves the latest of each.

Base API (robot head)  ──get_camera_frame()──▶  AvaFeedback :5001  ──▶  teleop GUI

Endpoints
  GET /feedback                      JSON summary (one record per camera for now)
  GET /cameras                       camera names
  GET /camera/<cam>/latest?after=N   newest JPEG if its frame number is > N, else 204
                                     headers: X-Frame-Seq, X-Frame-Age-Ms
"""
from __future__ import annotations

from werkzeug.serving import make_server


import threading
import time
from collections import deque
from typing import Callable

from flask import Flask, Response, jsonify, request


class AvaFeedback:
    on_feedback: Callable[[dict], None]

    def __init__(self, base, host: str = "0.0.0.0", port: int = 5001,
                 cameras: list[str] | None = None, camera_param: str = "10", max_fps: float = 15):
        self.base = base                      # anything with get_camera_frame(camera, param) -> bytes | None
        self.host, self.port = host, port
        self.cameras = cameras or ["top"]
        self.camera_param = str(camera_param)
        self.min_period = 1.0 / max_fps
        self.on_feedback = lambda feedback: None

        self._lock = threading.Lock()
        # camera -> {"seq", "t", "jpeg"}; seq counts frames received from the base, starting at 1
        self._frames: dict[str, dict] = {}
        self._arrivals = {cam: deque(maxlen=60) for cam in self.cameras}
        self._failures = {cam: 0 for cam in self.cameras}

    # -------- Loop threads -------- #

    def _camera_loop(self, cam: str):
        seq = 0
        while True:
            t0 = time.monotonic()
            jpeg = self.base.get_camera_frame(cam, self.camera_param)
            if jpeg:
                seq += 1
                now = time.monotonic()
                with self._lock:
                    self._frames[cam] = {"seq": seq, "t": now, "jpeg": jpeg}
                    self._arrivals[cam].append(now)
                self.on_feedback({"type": "camera_frame", "camera": cam, "seq": seq, "bytes": len(jpeg), "jpeg": jpeg})
            else:
                with self._lock:
                    self._failures[cam] += 1
                time.sleep(0.5)  # base unreachable; don't hammer it
            time.sleep(max(0.0, self.min_period - (time.monotonic() - t0)))

    def summary(self) -> dict:
        now = time.monotonic()
        out = {}
        with self._lock:
            for cam in self.cameras:
                f = self._frames.get(cam)
                recent = [t for t in self._arrivals[cam] if now - t <= 1.0]
                out[cam] = {
                    "frame": f["seq"] if f else 0,
                    "age_ms": round((now - f["t"]) * 1000) if f else None,
                    "fps": len(recent),
                    "failed_pulls": self._failures[cam],
                }
        return {"cameras": out}

    # ------ Core ------ #

    def create_app(self) -> Flask:
        app = Flask(__name__)
        app.json.sort_keys = False

        @app.get("/feedback")
        def feedback():
            return jsonify(self.summary())

        @app.get("/cameras")
        def cameras():
            return jsonify(self.cameras)

        @app.get("/camera/<cam>/latest")
        def latest(cam):
            if cam not in self.cameras:
                return jsonify(error=f"unknown camera '{cam}'"), 404
            after = request.args.get("after", default=0, type=int)
            with self._lock:
                f = self._frames.get(cam)
            if f is None or f["seq"] <= after:
                return Response(status=204)  # nothing newer than what the caller has
            return Response(f["jpeg"], mimetype="image/jpeg", headers={
                "X-Frame-Seq": str(f["seq"]),
                "X-Frame-Age-Ms": str(round((time.monotonic() - f["t"]) * 1000)),
                "Cache-Control": "no-store",
            })

        return app


    def start(self, block: bool = False):
        """Start one loop thread per camera and the HTTP server thread, then return.

        Pass block=True to wait here until stop() (or Ctrl+C) instead.
        """
        print(f"[Feedback] Starting AvaFeedback server on {self.host}:{self.port}...")
        # Binding happens here, on the caller's thread, so "port in use" raises immediately
        self._server = make_server(self.host, self.port, self.create_app(), threaded=True)
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="feedback-http")
        self._server_thread.start()
        for cam in self.cameras:
            threading.Thread(target=self._camera_loop, args=(cam,), daemon=True, name=f"camera-{cam}").start()
        print(f"AvaFeedback serving on http://{self.host}:{self.port}")
        if block:
            self.join()

    def join(self):
        """Wait until the server stops. Ctrl+C stops it."""
        try:
            while self._server_thread.is_alive():
                self._server_thread.join(timeout=0.5)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self._server.shutdown()