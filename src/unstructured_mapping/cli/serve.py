"""Start the Unstructured Mapping FastAPI server.

Usage::

    uv run python -m unstructured_mapping.cli.serve
    uv run python -m unstructured_mapping.cli.serve --reload
    uv run python -m unstructured_mapping.cli.serve --host 0.0.0.0 --port 8000

Requires the ``api`` optional extra::

    uv sync --extra api
"""

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Unstructured Mapping API server."
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Bind port (default: 8000)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on code changes (dev mode)",
    )
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print(
            "error: uvicorn is not installed. Run: uv sync --extra api",
            file=sys.stderr,
        )
        sys.exit(1)

    uvicorn.run(
        "unstructured_mapping.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
