import argparse
import os


def main():
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
        reload_dirs=[str(__import__("pathlib").Path(__file__).resolve().parents[1])]
        if args.reload
        else None,
        workers=1,
    )


if __name__ == "__main__":
    main()
