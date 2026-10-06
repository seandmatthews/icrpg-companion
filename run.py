"""Launch the table-companion server.

    python run.py            # serve on 0.0.0.0:8770, restore last snapshot
    python run.py --fresh    # ignore + delete the last snapshot, new session
"""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from server.app import create_app, detect_lan_ip

DEFAULT_PORT = 8770


def banner_lines(state, port: int, lan_ip: str | None, load_reason: str | None, data_dir: str) -> list[str]:
    gm_url = f"http://localhost:{port}"
    players_url = (
        f"http://{lan_ip}:{port}/join?room={state['room_code']}" if lan_ip else "(no LAN IP detected)"
    )
    lines = [
        "",
        "  ┌─────────────────────────────────────────────────┐",
        "  │  TABLE COMPANION                                │",
        "  ├─────────────────────────────────────────────────┤",
        f"  │  GM console : {gm_url:<34}│",
        f"  │  GM key     : {state['gm_token']:<34}│",
        f"  │  Room code  : {state['room_code']:<34}│",
        f"  │  Players    : {players_url:<34}│",
        "  └─────────────────────────────────────────────────┘",
        "  Keep this window open while you play. Ctrl+C to stop.",
        f"  Session snapshot: {data_dir}",
    ]
    if load_reason:
        lines.append(f"  NOTE: previous {load_reason}.")
    if not lan_ip:
        lines.append("  WARNING: LAN IP not detected — phones may not reach this server.")
        lines.append("  (Windows Mobile Hotspot is the reliable fallback network.)")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="ICRPG table companion server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--fresh", action="store_true", help="start a new session, discarding the last snapshot")
    parser.add_argument("--data-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    args = parser.parse_args()

    app = create_app(args.data_dir, fresh=args.fresh)
    state = app.state_model  # attribute set by create_app()

    lan_ip = detect_lan_ip()
    print("\n".join(banner_lines(state, args.port, lan_ip, getattr(app, "load_reason", None), args.data_dir)))
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
