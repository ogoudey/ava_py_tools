import requests
import syncing

class Interface:
    action_mapping: dict[str, dict[str, str]]
    controller_server: str

    def sync(self):
        # check /sync endpoint of controller server
        try:
            # Assuming an endpoint URL is defined, e.g., self.server_url
            response = requests.get(f"{self.controller_server}/sync", timeout=5)
            response.raise_for_status()
            server_data = response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error communicating with the controller server: {e}")
            return
        except ValueError:
            print("Error: Server response was not valid JSON.")
            return

        # Iterate through local action mapping and compare with server data
        for modality, action in self.action_mapping.items():
            modality_name = modality
            print(f"Syncing modality: {modality_name}")
            
            # Check if the modality exists in the server response
            if modality_name not in server_data:
                print(f"  [MISMATCH] Modality '{modality_name}' is missing from the server response.")
                continue
                
            server_actions = server_data[modality_name]

            for input_key, expected_unit in action.items():
                # Convert keys/values to strings for comparison as requested
                input_str = str(input_key)
                expected_str = str(expected_unit)
                
                # Check if the input exists in the server's action dict for this modality
                if input_str not in server_actions:
                    print(f"  [MISMATCH] Input '{input_str}' under '{modality_name}' is missing on the server.")
                    continue
                    
                actual_str = str(server_actions[input_str])

                # Compare the strings
                if actual_str != expected_str:
                    print(f"  [MISMATCH] For input '{input_str}' in '{modality_name}':")
                    print(f"    Expected: {expected_str}")
                    print(f"    Got     : {actual_str}")
                else:
                    print(f"  [MATCH] Input '{input_str}' is synchronized.")
