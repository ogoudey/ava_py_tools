from gui import AvaTeleopGUI
import requests
import argparse

AVA1_IP = "192.168.0.102"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev", action="store_true", help="Run in development mode")
    args = parser.parse_args()    

    host = AVA1_IP if not args.dev else "localhost"

    gui = AvaTeleopGUI(
        policy_server=f"http://{host}:5000",
        feedback_server=f"http://{host}:5001",
    )
    gui.start()

