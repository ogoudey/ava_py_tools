from interface import Interface
import requests
from pynput import keyboard

import syncing

class AvaTeleopGUI(Interface):
    action_mapping: dict[str, dict[str, str]] = {
        "movement": {
            "w": "forward",
            "s": "backward",
            "a": "strafe_left",
            "d": "strafe_right",
            "q": "rotate_left",
            "e": "rotate_right"
        }
    }
    def __init__(self):
        self.controller_server = "http://localhost:5000"
        self.sync()
    
    def _on_press(self, key):
        try:
            k = key.char.lower()
        except AttributeError:
            return

        # Send raw key to the server; state logic lives entirely on the backend
        try:
            response = requests.post(
                f"{self.controller_server}/command", 
                json={"action": self.action_mapping["movement"][k]}, 
                timeout=0.05
            )
            response.raise_for_status()
        except requests.exceptions.RequestException:
            # Drop silently or log network hiccups during rapid key inputs
            pass

    def _on_release(self, key):
        try:
            k = key.char.lower()
        except AttributeError:
            return

        # Send raw key to the server; state logic lives entirely on the backend
        try:
            response = requests.post(
                f"{self.controller_server}/stop", 
                json={"action": self.action_mapping["movement"][k]}, 
                timeout=0.05
            )
            response.raise_for_status()
        except requests.exceptions.RequestException:    
            # Drop silently or log network hiccups during rapid key inputs
            pass
            
    def start(self):
            # Listener blocks until ESC
            with keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release
            ) as listener:
                print(f"Joining Listener")
                listener.join()

if __name__ == "__main__":
    gui = AvaTeleopGUI()
    try:
        gui.sync()
    except Exception as e:
        print(f"GUI and policy actions do not sync! {e}")
    
