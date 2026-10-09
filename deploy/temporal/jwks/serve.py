# SPDX-License-Identifier: Apache-2.0
"""D12's key set server (2b-4b M4): serves the proof's JWKS file, read on every request so a rotated key set is
picked up, to the server's JWT claim mapper on the Compose network. Standard library only; the pinned Python image.
Configuration B's local proof only: a production key set is the owner's identity provider's, over HTTPS."""

import http.server
import os
import sys

KEYS = os.environ.get("DEWPOINT_JWKS_FILE", "/jwks/jwks.json")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/jwks.json":
            self.send_error(404)
            return
        try:
            with open(KEYS, "rb") as f:
                body = f.read()
        except OSError as e:
            print(f"jwks_unreadable {type(e).__name__}", file=sys.stderr)
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # requests aren't logged


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104
