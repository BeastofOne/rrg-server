#extra_requirements:
#requests

import requests as req

def main(
    target_node: str,
    command: str,
    user_message: str,
    chat_history: list,
    state: dict,
):
    url = "http://rrg-pnl:8100/process"
    payload = {
        "command": command,
        "user_message": user_message,
        "chat_history": chat_history,
        "state": state,
    }
    resp = req.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()
