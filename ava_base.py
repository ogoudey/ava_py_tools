import requests
from typing import Any, Dict, Optional, List
from PIL import Image
from io import BytesIO
import json
import time
import math

# =========================
# Configuration
# =========================
BASE_URL = "http://172.18.0.1"
TIMEOUT = 5.0  # seconds


# =========================
# Helper function
# =========================
def _safe_request(method: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Send a HTTP request safely.
    Returns JSON if possible, otherwise a dict describing the error.
    """
    url = BASE_URL.rstrip("/") + endpoint
    try:
        resp = requests.request(method, url, params=params, timeout=TIMEOUT)
        try:
            data = resp.json()
        except ValueError:
            data = {"error": "Non-JSON response", "text": resp.text}
        return {"ok": resp.ok, "status_code": resp.status_code, "data": data}
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "Timeout", "endpoint": endpoint}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "error": "ConnectionError", "endpoint": endpoint}
    except Exception as e:
        return {"ok": False, "error": str(e), "endpoint": endpoint}


# =========================
# Ava Base API Wrapper
# =========================
class AvaBaseAPI:
    """Ava Base HTTP API"""

    
    def drive_velocity(self,
                   translate: float = 0.0,
                   rotate: float = 0.0,
                   sidestep: float = 0.0,
                   duration: float = 0.1,
                   nudge: bool = False) -> Dict[str, Any]:
        """
        Sends a Drive Velocity command to Ava.

        Args:
            translate: forward/backward distance in meters
            rotate: rotation in radians
            duration: time to execute this command
            nudge: boolean, small-step flag
        """
        payload = {
            "translate": translate,
            "rotate": rotate,
            "sidestep": sidestep,
            "duration": duration,
            "nudge": nudge
        }
        return _safe_request("POST", "/robot/drive/velocity", payload)  

    def stop_robot(self) -> Dict[str, Any]:
        return _safe_request("POST", "/robot/drive/stopRobot")

    def get_position(self, include_local: bool = True, include_velocity: bool = True) -> Dict[str, Any]:
        params = {
            "includeLocal": str(include_local).lower(),
            "includeVelocity": str(include_velocity).lower()
        }
        return _safe_request("GET", "/robot/drive/position", params)


    # mapping -> localization mode 
    def localize(self, mapId: int = 1):
        params = {"mapId": mapId}
        return _safe_request("POST", f"/robot/mapping/localize", params)

    def drive_waypoint(self, points: List[Dict[str, Any]]):
        params = {"points": points}
        return _safe_request("POST", "/robot/drive/waypoints", params)

    def drive_destination(self, x: float, y: float, mapId: int,
                          theta: Optional[float] = None,
                          radius: Optional[float] = None,
                          orient_first: Optional[bool] = None) -> Dict[str, Any]:
        params = {"x": x, "y": y, "mapId": mapId}
        if theta is not None:
            params["theta"] = theta
        if radius is not None:
            params["radius"] = radius
        if orient_first is not None:
            params["orientFirst"] = str(orient_first).lower()
        return _safe_request("POST", "/robot/drive/destination", params)

    ########## Driving ############
    def drive_local_waypoint(self, x: float, y: float, theta: Optional[float] = None) -> Dict[str, Any]:
        params = {"x": x, "y": y}
        if theta is not None:
            params["theta"] = theta
        return _safe_request("POST", "/robot/drive/localWaypoint", params)

    def drive_updates(self) -> Dict[str, Any]:
        return _safe_request("GET", "/robot/drive/updates")
    
    ######## -------- Docking --------- ##########

    def get_dock_locations(self):
        return _safe_request("POST", "/robot/dock/getLocations")
    
    def dock(self) -> Dict[str, Any]:
        return _safe_request("POST", "/robot/dock/dock")

    def undock(self):
        # shouldn't be necessary
        return _safe_request("POST", "/robot/dock/undock")

    ######## -------- Statues --------- ############

    def dock_status(self) -> Dict[str, Any]:
        return _safe_request("GET", "/robot/dock/status")
    
    def health(self) -> Dict[str, Any]:
        return _safe_request("GET", "/robot/health")
    
    def info(self) -> Dict[str, Any]:
        return _safe_request("GET", "/robot/info")
    
    def behavior_state(self):
        return _safe_request("GET", "/robot/navigation/runningBehaviorState")
    
    ######### ------- Random ---------- ##########
    def get_point_forward_d(self, d):
        data = self.get_position()["data"]

        return {
            "x": float(data["x"]) + d * math.cos(float(data["theta"])),
            "y": float(data["y"]) + d * math.sin(float(data["theta"])),
        }
    
    ######### ---------- DB Stuff -------- ########33
    def import_db(self, path_to_db, new_db_name):
        with open(path_to_db) as f:
            j = json.loads(f.read())
        params = {
            "maps": j["maps"]
        }
        return _safe_request("POST", f"/robot/mapping/import/{new_db_name}", params) 
           
    
    ######### ------- Mapping ----- #########

    def resume_mapping(self):
        return _safe_request("GET", "/robot/mapping/resume")

    def get_map(self, mapId: int = 1):
        url = f"{BASE_URL}/robot/mapping/map/{mapId}"
        try:
            r = requests.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            return Image.open(BytesIO(r.content)).convert("RGB")
                
        except Exception as e:
            print(f"[get_map] Failed: {e}")
            return None 

    def get_map_list(self) -> Dict[str, Any]:
        return _safe_request("GET", "/robot/mapping/maps")

    def get_map_tile(self, map_id: int, x_idx: int, y_idx: int) -> Optional[Image.Image]:
        url = f"{BASE_URL}/robot/mapping/tile/{map_id}/{x_idx}/{y_idx}"
        try:
            r = requests.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            return Image.open(BytesIO(r.content)).convert("L")
        except Exception as e:
            print(f"[get_map_tile] Failed ({map_id}, {x_idx}, {y_idx}): {e}")
            return None

    def create_new_map(self, desc: str) -> Dict[str, Any]:
        params = {"desc": desc}
        return _safe_request("POST", "/robot/mapping/newmap", params)

    def mapping_updates(self):
        return _safe_request("GET", "/robot/mapping/updates")

    def delete_map(self, mapId: int):
        return _safe_request("GET", f"/robot/mapping/deleteMap/{mapId}")
    
    ############# Tagging ############
    def assign_dock_attribute_to_tag(self, tagId):
        """
        Doesn't work
        """
        params = {
            
            "attributes": {"TagType": "Dock"}
        }
        return _safe_request("POST", f"/robot/annotation/updatetag/", params)

    def list_tags(self, mapId: int):
        return _safe_request("GET", f"/robot/annotation/tags/{mapId}")

    def create_tag(self, mapId, name: str, x: float = -0.06708815205076975, y: float = -0.03280086927553744, theta: Optional[float] = None, attributes: Optional[dict]=None):
        
        params = {'x': x, 'y': y, 'name': name}
        if theta is not None:
            params['theta'] = theta
        if attributes is not None:
            print(f"Assigning attributes {attributes}")
            params["attributes"] = attributes
        
        return _safe_request("GET", f"/robot/annotation/createTag/{mapId}", params)

    def delete_tag(self, mapId, tagId):
        return _safe_request("GET", f"/robot/annotation/deleteTag/{mapId}/{tagId}")

    def drive_to_tag(self, mapId: int, tagId: int) -> Dict[str, Any]:
        print(f"[ava_base] Sending /robot/drive/driveToTag/{mapId}/{tagId}")
        return _safe_request("POST", f"/robot/drive/driveToTag/{mapId}/{tagId}")

    def get_perception(self):
        url = f"{BASE_URL}/robot/mapping/lps"
        try:
            r = requests.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            return Image.open(BytesIO(r.content)).convert("L")
                
        except Exception as e:
            print(f"[get_perception] Failed: {e}")
            return None
        
    # Composite functions

    ## Not actually smart
    def smart_dock(self):
        t0 = time.time()
        self.drive_to_tag(5, 18)
        while not "COMPLETE" in self.drive_updates()["data"]["status"].values():
            time.sleep(1)
        print("Reached Dock tag")
        while not self.dock_status()["data"]["state"] == "Docked":
            self.dock()
            time.sleep(1)
            print(self.dock_status()["data"]["status"])
            while self.dock_status()["data"]["status"] == "IN_PROGRESS":
                time.sleep(1)
            print(f"Retrying dock {time.time() - t0}")


ava = AvaBaseAPI()



