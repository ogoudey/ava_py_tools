"""Browser teleop for the Ava mobile base.

Run:  python teleop_web.py --controller http://localhost:5000
Open: http://localhost:8080

The browser captures key presses and releases and sends each one here as a single
discrete event. This server maps key -> action using `action_mapping` (the same table
that `Interface.sync()` checks), forwards it to the controller, and reports back
exactly what happened to that event. It also proxies the robot's camera route
(robot/streaming/camera/<cam>/<param>/<timestamp>) so the page can use the same
relative path the native robot UI uses.
"""

from __future__ import annotations

import argparse
import itertools
import threading
import time
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request, stream_with_context

from interface import Interface

STATIC_DIR = Path(__file__).parent / "static"


class AvaTeleopGUI(Interface):
    action_mapping: dict[str, dict[str, str]] = {
        "movement": {
            "w": "forward",
            "s": "backward",
            "a": "strafe_left",
            "d": "strafe_right",
            "q": "rotate_left",
            "e": "rotate_right",
        }
    }

    def __init__(
        self,
        policy_server: str,
        feedback_server: str,
        cameras: list[str] | None = None,
        camera_param: str = "10",
        command_timeout: float = 0.05,
        stop_timeout: float = 0.1,
        stop_attempts: int = 2,
    ):
        self.policy_server = policy_server.rstrip("/")
        self.feedback_server = feedback_server.rstrip("/")
        # Host serving robot/streaming/... ; defaults to the controller
        self.cameras = cameras or ["top"]
        self.camera_param = str(camera_param)
        self.command_timeout = command_timeout
        self.stop_timeout = stop_timeout
        self.stop_attempts = max(1, stop_attempts)

        self._seq = itertools.count(1)
        self._feedback_seq = itertools.count(1)
        self._lock = threading.Lock()
        self._local = threading.local()

    # -------- Helpers -------- #

    def _session(self) -> requests.Session:
        # One keep-alive session per server thread
        s = getattr(self._local, "session", None)
        if s is None:
            s = self._local.session = requests.Session()
        return s

    def _next(self, counter) -> int:
        with self._lock:
            return next(counter)

    def resolve(self, key: str) -> tuple[str, str] | None:
        """(modality, action) bound to this key, or None if the key is unmapped."""
        key = key.lower()
        for modality, table in self.action_mapping.items():
            if key in table:
                return modality, table[key]
        return None

    def camera_url(self, cam: str, ts_ms: int | None = None) -> str:
        ts_ms = ts_ms if ts_ms is not None else int(time.time() * 1000)
        return f"{self.feedback_server}/robot/streaming/camera/{cam}/{self.camera_param}/{ts_ms}"

    # -------- Keyboard control -------- #

    def send_edge(self, key: str, edge: str) -> dict:
        """Forward one key edge ("press" -> /command, "release" -> /stop) and describe the outcome.

        status is one of: ack, rejected, timeout, unreachable, unmapped.
        """
        record = {"seq": self._next(self._seq), "key": key, "edge": edge, "t": time.time()}
        binding = self.resolve(key)
        if binding is None:
            record["status"] = "unmapped"
            return record
        modality, action = binding
        record.update(modality=modality, action=action)

        if edge == "press":
            path, timeout, attempts = "/command", self.command_timeout, 1
        else:
            # A lost stop leaves the base moving, so it gets a little more time and a retry
            path, timeout, attempts = "/stop", self.stop_timeout, self.stop_attempts

        t0 = time.perf_counter()
        status, detail, http, attempt = "unreachable", None, None, 0
        for attempt in range(1, attempts + 1):
            try:
                r = self._session().post(f"{self.policy_server}{path}", json={"action": action}, timeout=timeout)
                http = r.status_code
                r.raise_for_status()
                status, detail = "ack", None
                break
            except requests.exceptions.HTTPError:
                status, detail = "rejected", f"HTTP {http}"
                break  # the controller answered; retrying won't change its mind
            except requests.exceptions.Timeout:
                status, detail = "timeout", f"no reply within {timeout * 1000:.0f} ms"
            except requests.exceptions.RequestException as e:
                status, detail = "unreachable", type(e).__name__

        record.update(status=status, detail=detail, http=http, attempts=attempt,
                      ms=round((time.perf_counter() - t0) * 1000, 1))
        return record

    # -------- Feedback -------- #

    def fetch_feedback(self) -> dict:
        record = {"seq": self._next(self._feedback_seq), "t": time.time()}
        t0 = time.perf_counter()
        try:
            r = self._session().get(f"{self.feedback_server}/feedback", timeout=0.1)
            r.raise_for_status()
            record.update(status="ok", data=r.json())
        except ValueError:
            record.update(status="malformed", detail="feedback was not valid JSON")
        except requests.exceptions.RequestException as e:
            record.update(status="unreachable", detail=type(e).__name__)
        record["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return record

    # ------ Core ------ #

    def config(self) -> dict:
        return {
            "action_mapping": self.action_mapping,
            "cameras": self.cameras,
            "camera_param": self.camera_param,
            "policy_server": self.policy_server,
            "feedback_server": self.feedback_server,
        }
    
    def start(self, host: str = "127.0.0.1", port: int = 8080):
        """Check bindings, then serve the teleop page. Blocks until Ctrl+C."""
        report = self.sync()
        if report["reachable"] and any(b["status"] != "match" for b in report["bindings"]):
            print("GUI and policy actions do not sync! See the Bindings panel.")
        print(f"Teleop page: http://{host}:{port}")
        create_app(self).run(host=host, port=port, threaded=True)



def create_app(gui: AvaTeleopGUI) -> Flask:
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    app.json.sort_keys = False  # keep action_mapping in the order it was written

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/config")
    def config():
        return jsonify(gui.config())

    @app.get("/api/sync")
    def sync():
        return jsonify(gui.sync_report())

    @app.post("/api/key")
    def key():
        body = request.get_json(silent=True) or {}
        k, edge = str(body.get("key", "")).lower(), body.get("edge")
        if not k or edge not in ("press", "release"):
            return jsonify(error="expected {key, edge: press|release}"), 400
        record = gui.send_edge(k, edge)
        record["client_seq"] = body.get("client_seq")
        return jsonify(record)

    @app.get("/api/feedback")
    def feedback():
        return jsonify(gui.fetch_feedback())

    @app.get("/api/camera/<cam>/probe")
    def camera_probe(cam):
        """Tells the page whether the camera route returns single frames or an MJPEG stream."""
        try:
            with requests.get(gui.camera_url(cam), stream=True, timeout=(1, 2)) as r:
                ctype = r.headers.get("Content-Type", "")
                mode = "stream" if "multipart" in ctype.lower() else "snapshot"
                return jsonify(ok=r.ok, http=r.status_code, content_type=ctype, mode=mode)
        except requests.exceptions.RequestException as e:
            return jsonify(ok=False, error=type(e).__name__, mode="snapshot")

    @app.get("/robot/streaming/<path:rest>")
    def camera_proxy(rest):
        """Same relative route as the native robot UI, passed through to the robot API."""
        url = f"{gui.robot_api}/robot/streaming/{rest}"
        if request.query_string:
            url += "?" + request.query_string.decode()
        try:
            upstream = requests.get(url, stream=True, timeout=(1, 5))
        except requests.exceptions.RequestException as e:
            return Response(f"camera unreachable: {type(e).__name__}", status=502, mimetype="text/plain")

        def relay():
            try:
                yield from upstream.iter_content(chunk_size=16384)
            finally:
                upstream.close()

        return Response(
            stream_with_context(relay()),
            status=upstream.status_code,
            content_type=upstream.headers.get("Content-Type", "application/octet-stream"),
            headers={"Cache-Control": "no-store"},
        )

    return app


def main():
    p = argparse.ArgumentParser(description="Browser teleop for the Ava mobile base")
    p.add_argument("--controller", default="http://localhost:5000", help="controller server URL")
    p.add_argument("--robot-api", default=None, help="host serving robot/streaming/... (defaults to --controller)")
    p.add_argument("--camera", action="append", dest="cameras", help="camera name, repeatable (default: top)")
    p.add_argument("--camera-param", default="10", help="the segment after the camera name in the stream route")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()

    gui = AvaTeleopGUI(args.controller, robot_api=args.robot_api,
                       cameras=args.cameras, camera_param=args.camera_param)
    report = gui.sync()
    if report["reachable"] and any(b["status"] != "match" for b in report["bindings"]):
        print("GUI and policy actions do not sync! See the Bindings panel.")

    print(f"Teleop page: http://{args.host}:{args.port}")
    create_app(gui).run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()