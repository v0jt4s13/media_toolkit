"""Run the Media Toolkit Flask application."""
from __future__ import annotations

import os
import socket

from . import create_app

def _find_free_port(start_port: int = 5000, max_tries: int = 20) -> int:
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("Nie znaleziono wolnego portu")


def main() -> None:
    app = create_app()

    host = os.getenv("FLASK_HOST", "0.0.0.0")
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    port_env = os.getenv("FLASK_PORT") or os.getenv("PORT")
    port = int(port_env) if port_env else _find_free_port()

    print(f"Uruchamianie Media Toolkit na porcie {port}...")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":  # pragma: no cover
    main()
