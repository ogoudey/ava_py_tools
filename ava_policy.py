from flask import request, jsonify, Flask
import logging
logger = logging.getLogger('werkzeug')
logger.setLevel(logging.WARNING)

import math
import threading
import time

import ava_base as ab


class Policy:
    #input_mapping: dict[syncing.Modality, dict[str, syncing.ModalityUnit]]
    input_mapping: dict[str, dict[str, str]]


class AvaPolicy(Policy):
    pass


class AvaTeleopPolicy(AvaPolicy):
    """
    WASD teleop for Gen1 Ava using Drive Velocity Robot Service.

    Each held action adds its velocity; the command sent to the base is the sum of
    all held actions, so W+D drives diagonally, W+Q arcs, and W+S cancels out.
    """
    input_mapping = {
        "movement": {
            "w": "forward",
            "s": "backward",
            "a": "strafe_left",
            "d": "strafe_right",
            "q": "rotate_left",
            "e": "rotate_right"
        }
    }

    def __init__(self, base: ab.AvaBaseAPI, host="0.0.0.0", port=5000):
        self.app = Flask(__name__)
        self.host = host
        self.port = port
        self.base = base

        self.speed = 0.1
        self.lateral_speed = 0.1
        self.rot_speed = 0.1
        # Cap on combined translate+sidestep, so a diagonal isn't faster than straight
        self.max_linear = max(self.speed, self.lateral_speed)

        # action -> (translate, sidestep, rotate) contribution while held
        self.velocity = {
            "forward":      ( self.speed, 0.0, 0.0),
            "backward":     (-self.speed, 0.0, 0.0),
            "strafe_left":  (0.0,  self.lateral_speed, 0.0),
            "strafe_right": (0.0, -self.lateral_speed, 0.0),
            "rotate_left":  (0.0, 0.0,  self.rot_speed),
            "rotate_right": (0.0, 0.0, -self.rot_speed),
        }
        # Every mapped action must have a velocity, or it would be accepted and do nothing
        missing = {a for m in self.input_mapping.values() for a in m.values()} - self.velocity.keys()
        if missing:
            raise ValueError(f"input_mapping has actions with no velocity: {sorted(missing)}")

        self._active: set[str] = set()   # actions currently held
        self._lock = threading.Lock()
        self.running = True
        self._register_routes()

    def start(self):
        """Starts the Flask server and the command runner."""
        threading.Thread(target=self.command_runner, daemon=True).start()
        logger.info(f"[Policy] Starting Flask server... on {self.port}")
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)

    def _register_routes(self):
        """Maps endpoints to instance methods."""
        self.app.add_url_rule('/health', 'health', self.health, methods=['GET'])
        self.app.add_url_rule('/sync', 'sync', self.sync, methods=['GET'])
        self.app.add_url_rule('/command', 'command', self.receive_command, methods=['POST'])
        self.app.add_url_rule('/stop', 'stop', self.receive_stop, methods=['POST'])

    def health(self):
        """Health check endpoint."""
        return jsonify({"status": "healthy"}), 200

    def sync(self):
        """Returns the modality -> action string mappings for client verification."""
        return jsonify(self.input_mapping), 200

    # -------- Command state -------- #

    def current_cmd(self) -> dict:
        """Sum of the velocities of all held actions."""
        with self._lock:
            active = tuple(self._active)
        t = sum(self.velocity[a][0] for a in active)
        s = sum(self.velocity[a][1] for a in active)
        r = sum(self.velocity[a][2] for a in active)
        n = math.hypot(t, s)
        if n > self.max_linear:
            t, s = t * self.max_linear / n, s * self.max_linear / n
        return {"translate": t, "sidestep": s, "rotate": r}

    def _read_action(self):
        data = request.get_json(silent=True)
        if not data or "action" not in data:
            return None, (jsonify({"error": "Invalid payload"}), 400)
        action = data["action"]
        if action not in self.velocity:
            # Reject instead of acknowledging, so the GUI shows it as rejected
            return None, (jsonify({"error": f"Unknown action '{action}'"}), 400)
        return action, None

    def receive_command(self):
        action, error = self._read_action()
        if error:
            return error
        with self._lock:
            self._active.add(action)
            active = sorted(self._active)
        cmd = self.current_cmd()
        logger.info(f"Action '{action}' pressed. Active: {active} -> {cmd}")
        return jsonify({"status": "success", "active": active, "cmd": cmd}), 200

    def receive_stop(self):
        action, error = self._read_action()
        if error:
            return error
        with self._lock:
            self._active.discard(action)   # only this action; others stay held
            active = sorted(self._active)
        cmd = self.current_cmd()
        logger.info(f"Action '{action}' released. Active: {active} -> {cmd}")
        return jsonify({"status": "success", "active": active, "cmd": cmd}), 200

    def command_runner(self):
        moving = False
        while self.running:
            try:
                cmd = self.current_cmd()
                # Only send command if any component is non-zero
                if any(abs(v) > 1e-6 for v in cmd.values()):
                    x = self.base.drive_velocity(
                        translate=cmd["translate"],
                        sidestep=cmd["sidestep"],
                        rotate=cmd["rotate"],
                        duration=0.2,    # outlives one 0.1 s tick, so no gaps while held
                        nudge=True      # default
                    )
                    moving = True
                    print(f"{cmd} => {x}", end="\r")
                elif moving:
                    # Last key released (or opposites cancel): stop now instead of coasting out the 0.2 s
                    self.base.stop_robot()
                    moving = False
            except Exception as e:
                print("Could not reach API:", e)
            time.sleep(0.1)  # 10 Hz


if __name__ == "__main__":
    teleop = AvaTeleopPolicy(ab.AvaBaseAPI())
    teleop.start()