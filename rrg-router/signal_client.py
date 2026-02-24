"""Client for reading and acting on signals via Windmill scripts."""

import requests
from typing import List, Dict, Any, Optional


class SignalClient:
    """Polls jake_signals table via Windmill scripts.

    Uses f/switchboard/read_signals and f/switchboard/act_signal
    to interact with the signal queue.
    """

    def __init__(
        self,
        windmill_base_url: str,
        windmill_token: str,
        workspace: str = "rrg",
        timeout: int = 15,
    ):
        self.base_url = windmill_base_url.rstrip("/")
        self.token = windmill_token
        self.workspace = workspace
        self.timeout = timeout

    def _run_script(self, script_path: str, args: dict) -> Any:
        """Run a Windmill script synchronously and return result."""
        url = (
            f"{self.base_url}/api/w/{self.workspace}"
            f"/jobs/run_wait_result/p/{script_path}"
        )
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, json=args, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_pending_signals(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch pending signals from the queue."""
        try:
            return self._run_script(
                "f/switchboard/read_signals",
                {"status": "pending", "limit": limit},
            )
        except Exception:
            return []

    def act_on_signal(
        self, signal_id: int, action: str, acted_by: str = "jake"
    ) -> Dict[str, Any]:
        """Mark a signal as acted upon."""
        return self._run_script(
            "f/switchboard/act_signal",
            {"signal_id": signal_id, "action": action, "acted_by": acted_by},
        )

    def resume_flow(self, resume_url: str, payload: dict = None) -> bool:
        """Resume a suspended Windmill flow by POSTing to its resume URL."""
        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
            resp = requests.post(
                resume_url,
                json=payload or {},
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False
