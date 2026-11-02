import requests


class Interface:
    """Base class for all teleop interfaces.

    `action_mapping` is the explicit contract: {modality: {input: robot_action}}.
    `sync()` checks that contract against the controller's /sync endpoint.
    """

    action_mapping: dict[str, dict[str, str]]
    policy_server: str

    def sync_report(self) -> dict:
        """Compare the local action mapping with the controller's, one record per binding.

        Returns {"reachable": bool, "error": str | None, "bindings": [...]}, where each
        binding is {"modality", "input", "expected", "actual", "status"} and status is
        one of "match", "mismatch", "missing_input", "missing_modality".
        """
        try:
            response = requests.get(f"{self.policy_server}/sync", timeout=5)
            response.raise_for_status()
            server_data = response.json()
        except requests.exceptions.RequestException as e:
            return {"reachable": False, "error": f"Error communicating with the controller server: {e}", "bindings": []}
        except ValueError:
            return {"reachable": False, "error": "Server response was not valid JSON.", "bindings": []}

        bindings = []
        for modality_name, action in self.action_mapping.items():
            server_actions = server_data.get(modality_name)
            for input_key, expected_unit in action.items():
                # Keys/values compared as strings, as before
                input_str, expected_str = str(input_key), str(expected_unit)
                record = {"modality": modality_name, "input": input_str, "expected": expected_str, "actual": None}
                if server_actions is None:
                    record["status"] = "missing_modality"
                elif input_str not in server_actions:
                    record["status"] = "missing_input"
                else:
                    record["actual"] = str(server_actions[input_str])
                    record["status"] = "match" if record["actual"] == expected_str else "mismatch"
                bindings.append(record)
        return {"reachable": True, "error": None, "bindings": bindings}

    def sync(self) -> dict:
        """Print the sync report (same messages as before) and return it."""
        report = self.sync_report()
        if not report["reachable"]:
            print(f"Error: {report['error']}")
            return report

        current = None
        for b in report["bindings"]:
            if b["modality"] != current:
                current = b["modality"]
                print(f"Syncing modality: {current}")
                if b["status"] == "missing_modality":
                    print(f"  [MISMATCH] Modality '{current}' is missing from the server response.")
            if b["status"] == "missing_modality":
                continue
            if b["status"] == "missing_input":
                print(f"  [MISMATCH] Input '{b['input']}' under '{current}' is missing on the server.")
            elif b["status"] == "mismatch":
                print(f"  [MISMATCH] For input '{b['input']}' in '{current}':")
                print(f"    Expected: {b['expected']}")
                print(f"    Got     : {b['actual']}")
            else:
                print(f"  [MATCH] Input '{b['input']}' is synchronized.")
        return report