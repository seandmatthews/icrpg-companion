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
    gm_url = f"http://localhost:{args.port}"
    players_url = (
        f"http://{lan_ip}:{args.port}/join?room={state['room_code']}" if lan_ip else "(no LAN IP detected)"
    )

    print()
    print("  ┌─────────────────────────────────────────────────┐")
    print("  │  TABLE COMPANION                                │")
    print("  ├─────────────────────────────────────────────────┤")
    print(f"  │  GM console : {gm_url:<34}│")
    print(f"  │  GM key     : {state['gm_token']:<34}│")
    print(f"  │  Room code  : {state['room_code']:<34}│")
    print(f"  │  Players    : {players_url:<34}│")
    print("  └─────────────────────────────────────────────────┘")
    print("  Keep this window open while you play. Ctrl+C to stop.")
    print(f"  Session snapshot: {args.data_dir}")
    if not lan_ip:
        print("  WARNING: LAN IP not detected — phones may not reach this server.")
        print("  (Windows Mobile Hotspot is the reliable fallback network.)")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
