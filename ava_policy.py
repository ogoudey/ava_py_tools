from dataclasses import dataclass
from typing import Optional
from flask import request, jsonify, Flask


import threading
import time
from typing import List
import syncing

import ava_base as ab

ava = None

class Policy:
    #input_mapping: dict[syncing.Modality, dict[str, syncing.ModalityUnit]]
    input_mapping: dict[str, dict[str, str]]
    pass

class AvaPolicy(Policy):
    pass

class AvaTeleopPolicy(AvaPolicy):
    """
    WASD teleop for Gen1 Ava using Drive Velocity Robot Service.
    """
    input_mapping = {
        "movement": {
            "w": "translate_forward",
            "s": "translate_backward",
            "a": "sidestep_left",
            "d": "sidestep_right",
            "q": "rotate_ccw",
            "e": "rotate_cw"
        }
    }
    def __init__(self, base: ab.AvaBaseAPI, host="0.0.0.0", port=5000):
        self.app = Flask(__name__)
        self.host = host
        self.port = port
        self.base = base

        self.speed = 0.1
        self.lateral_speed = 0.1
        self.rot_speed = 0.1  # optional, could map QE for rotation
        self.current_cmd = {
            "translate": 0.0,
            "sidestep": 0.0,
            "rotate": 0.0
        }
        self.running = True
        self._register_routes()
        self.base = None

    def start(self):
        """Starts the Flask server and the command runner."""
        threading.Thread(target=self.command_runner, daemon=True).start()
        print(f"[Policy] Starting Flask server... on {self.port}")
        self.app.run(host=self.host, port=self.port, debug=True, use_reloader=False)

    def _register_routes(self):
        """Maps endpoints to instance methods."""
        self.app.add_url_rule('/health', 'health', self.health, methods=['GET'])
        self.app.add_url_rule('/sync', 'sync', self.sync, methods=['GET'])
        self.app.add_url_rule('/command', 'command', self.receive_command, methods=['POST'])

    def health(self):
        """Health check endpoint."""
        return jsonify({"status": "healthy"}), 200

    def sync(self):
        """Returns the modality -> action string mappings for client verification."""
        return jsonify(self.input_mapping), 200

    def receive_command(self):
        data = request.json
        if not data or "action" not in data:
            return jsonify({"error": "Invalid payload"}), 400

        action = data["action"]

        # Reset or compute command based on server-side variables
        self.cmd = {"translate": 0.0, "sidestep": 0.0, "rotate": 0.0}

        if action == "forward":
            self.cmd["translate"] = self.speed
        elif action == "backward":
            self.cmd["translate"] = -self.speed
        elif action == "strafe_left":
            self.cmd["sidestep"] = self.lateral_speed
        elif action == "strafe_right":
            self.cmd["sidestep"] = -self.lateral_speed
        elif action == "rotate_left":
            self.cmd["rotate"] = self.rot_speed
        elif action == "rotate_right":
            self.cmd["rotate"] = -self.rot_speed

        print(f"Action '{action}' received. Updated server state: {self.cmd}")
        return jsonify({"status": "success", "current_cmd": self.cmd}), 200

    def receive_stop(self):
        data = request.json
        if not data or "action" not in data:
            return jsonify({"error": "Invalid payload"}), 400

        action = data["action"]

        # Reset or compute command based on server-side variables
        self.cmd = {"translate": 0.0, "sidestep": 0.0, "rotate": 0.0}

        if action == "forward":
            self.cmd["translate"] = 0.0
        elif action == "backward":
            self.cmd["translate"] = 0.0
        elif action == "strafe_left":
            self.cmd["sidestep"] = 0.0
        elif action == "strafe_right":
            self.cmd["sidestep"] = 0.0
        elif action == "rotate_left":
            self.cmd["rotate"] = 0.0
        elif action == "rotate_right":
            self.cmd["rotate"] = 0.0

        print(f"Action '{action}' received. Updated server state: {self.cmd}")
        return jsonify({"status": "success", "current_cmd": self.cmd}), 200
            
    def command_runner(self):
        while self.running:
            try:
                # Only send command if any component is non-zero
                if any(abs(v) > 1e-6 for v in self.current_cmd.values()):
                    x = self.base.drive_velocity(
                        translate=self.current_cmd.get("translate", 0.0),
                        sidestep=self.current_cmd.get("sidestep", 0.0),
                        rotate=self.current_cmd.get("rotate", 0.0),
                        duration=1.0,    # safe fixed duration
                        nudge=False      # default
                    )

                    print(f"{self.current_cmd} => {x}", end="\r")
            except Exception as e:
                print("Could not reach API:", e)
            time.sleep(0.1)  # 10 Hz


if __name__ == "__main__":
    teleop = AvaTeleopPolicy()
    teleop.run()
