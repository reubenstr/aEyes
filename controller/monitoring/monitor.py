#!/usr/bin/env python3
"""Main entry point for the standalone monitoring API."""

import argparse
import os
from pathlib import Path
import sys


def main():
    # Make controller modules importable when launched as a script, including in
    # Uvicorn's reload subprocess, regardless of the working directory.
    controller_dir = str(Path(__file__).resolve().parents[1])
    if __package__ in (None, ""):
        sys.path.insert(0, controller_dir)

    parser = argparse.ArgumentParser(
        description="aEyes monitoring API (independent of the controller)"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--reload", action="store_true", help="Reload backend code during development"
    )
    args = parser.parse_args()
    os.environ["AEYES_MONITOR_PORT"] = str(args.port)
    import uvicorn

    uvicorn.run(
        "monitoring.server:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[controller_dir] if args.reload else None,
        workers=1,
    )


if __name__ == "__main__":
    main()
