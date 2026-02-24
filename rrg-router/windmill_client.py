"""HTTP client for routing worker calls through Windmill."""

import base64
import requests
from typing import Optional, Dict, Any


class WindmillClient:
    """Client that routes worker calls through a Windmill flow.

    Drop-in replacement for WorkerNodeClient — same call_worker() signature.
    Calls Windmill's synchronous webhook endpoint which runs the
    f/switchboard/message_router flow (branchone routing to worker containers).
    """

    def __init__(
        self,
        windmill_base_url: str,
        windmill_token: str,
        workspace: str = "rrg",
        timeout: int = 180,
    ):
        self.base_url = windmill_base_url.rstrip("/")
        self.token = windmill_token
        self.workspace = workspace
        self.timeout = timeout

    def call_worker(
        self,
        handler_name: str,
        command: str,
        user_message: str,
        chat_history: list,
        state: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """Call a worker node via the Windmill message_router flow.

        Returns:
            {response, state, active, pdf_bytes, pdf_filename, error}
        """
        url = (
            f"{self.base_url}/api/w/{self.workspace}"
            f"/jobs/run_wait_result/f/f/switchboard/message_router"
        )
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "target_node": handler_name,
            "command": command,
            "user_message": user_message,
            "chat_history": chat_history,
            "state": state or {},
        }

        try:
            resp = requests.post(
                url, json=payload, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()

            # Decode PDF if present
            pdf_bytes = None
            if data.get("pdf_bytes"):
                try:
                    pdf_bytes = base64.b64decode(data["pdf_bytes"])
                except Exception:
                    pass

            return {
                "response": data.get("response", ""),
                "state": data.get("state", {}),
                "active": data.get("active", False),
                "pdf_bytes": pdf_bytes,
                "pdf_filename": data.get("pdf_filename"),
                "error": None,
            }

        except requests.Timeout:
            return {
                "response": f"Worker {handler_name} timed out (via Windmill). Please try again.",
                "state": state or {},
                "active": False,
                "pdf_bytes": None,
                "pdf_filename": None,
                "error": "timeout",
            }
        except requests.RequestException as e:
            return {
                "response": f"Failed to reach {handler_name} worker via Windmill: {e}",
                "state": state or {},
                "active": False,
                "pdf_bytes": None,
                "pdf_filename": None,
                "error": str(e),
            }
