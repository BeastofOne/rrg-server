"""HTTP client for communicating with worker node containers."""

import base64
import requests
from typing import Optional, Dict, Any


class WorkerNodeClient:
    """Client for calling worker node /process endpoints."""

    def __init__(self, worker_urls: Dict[str, str], timeout: int = 120):
        self.worker_urls = worker_urls
        self.timeout = timeout

    def call_worker(
        self,
        handler_name: str,
        command: str,
        user_message: str,
        chat_history: list,
        state: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """Call a worker node's /process endpoint.

        Returns:
            {response, state, active, pdf_bytes, pdf_filename, error}
        """
        if handler_name not in self.worker_urls:
            return {
                "response": f"Unknown worker: {handler_name}",
                "state": state or {},
                "active": False,
                "pdf_bytes": None,
                "pdf_filename": None,
                "error": f"Unknown worker: {handler_name}",
            }

        url = f"{self.worker_urls[handler_name]}/process"
        payload = {
            "command": command,
            "user_message": user_message,
            "chat_history": chat_history,
            "state": state or {},
        }

        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
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
                "response": f"Worker {handler_name} timed out. Please try again.",
                "state": state or {},
                "active": False,
                "pdf_bytes": None,
                "pdf_filename": None,
                "error": "timeout",
            }
        except requests.RequestException as e:
            return {
                "response": f"Failed to reach {handler_name} worker: {e}",
                "state": state or {},
                "active": False,
                "pdf_bytes": None,
                "pdf_filename": None,
                "error": str(e),
            }
