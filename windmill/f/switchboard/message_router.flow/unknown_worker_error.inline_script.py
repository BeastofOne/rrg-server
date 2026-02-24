def main(target_node: str, state: dict = {}):
    return {
        "response": f"Unknown worker: {target_node}",
        "state": state,
        "active": False,
        "pdf_bytes": None,
        "pdf_filename": None,
    }
