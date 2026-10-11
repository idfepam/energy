"""Serve docs/dashboard locally with caching disabled.

python -m http.server lets browsers reuse stale scripts after a rebuild, so a
fresh index.html can run against last build's data.js. This server marks every
response no-store.

    python3 scripts/serve_dashboard.py [port]
"""

from __future__ import annotations

import functools
import http.server
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "docs" / "dashboard"


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    handler = functools.partial(NoCacheHandler, directory=str(ROOT))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"Dashboard: http://localhost:{port}/")
        server.serve_forever()


if __name__ == "__main__":
    main()
