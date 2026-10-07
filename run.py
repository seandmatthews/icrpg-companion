"""Launch the table-companion server.

    python run.py            # serve on 0.0.0.0:8770, restore last snapshot
    python run.py --fresh    # start a new session; the old snapshot is only
                             # deleted once the first action commits (ticket 46)
"""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from server.app import create_app, detect_lan_candidates

DEFAULT_PORT = 8770


def banner_lines(
    state,
    port: int,
    lan_ip: str | None,
    load_reason: str | None,
    data_dir: str,
    alternates: list[str] | None = None,
) -> list[str]:
    gm_url = f"http://localhost:{port}"
    players_url = (
        f"http://{lan_ip}:{port}/join?room={state['room_code']}" if lan_ip else "(no LAN IP detected)"
    )
    # box width follows the longest row — long URLs must not break the frame
    rows = [
        f"GM console : {gm_url}",
        f"GM key     : {state['gm_token']}",
        f"Room code  : {state['room_code']}",
        f"Players    : {players_url}",
    ]
    width = max(len(r) for r in rows)
    lines = [
        "",
        f"  ┌{'─' * (width + 2)}┐",
        f"  │ {'TABLE COMPANION'.ljust(width)} │",
        f"  ├{'─' * (width + 2)}┤",
    ]
    for r in rows:
        lines.append(f"  │ {r.ljust(width)} │")
    lines += [
        f"  └{'─' * (width + 2)}┘",
        "  Keep this window open while you play. Ctrl+C to stop.",
        f"  Session snapshot: {data_dir}",
        "  (The join URL is fixed at boot — re-open Show QR after a network change.)",
    ]
    if load_reason:
        lines.append(f"  NOTE: previous {load_reason}.")
    if alternates and lan_ip:
        others = [a for a in alternates if a != lan_ip]
        if others:
            lines.append(f"  If phones can't reach {lan_ip}, try: {', '.join(others)}")
    if not lan_ip:
        lines.append("  WARNING: LAN IP not detected — phones may not reach this server.")
        lines.append("  (Windows Mobile Hotspot is the reliable fallback network.)")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="ICRPG table companion server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--fresh", action="store_true", help="start a new session; the old snapshot is deleted only once the first action commits")
    parser.add_argument("--data-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    args = parser.parse_args()

    # the LAN address is computed ONCE at boot (ticket 47): a blocking DNS
    # call inside /api/bootstrap froze the whole event loop on unhappy DNS
    candidates = detect_lan_candidates()
    lan_ip = candidates[0] if candidates else None
    app = create_app(args.data_dir, fresh=args.fresh, lan_ip=lan_ip)
    state = app.state_model  # attribute set by create_app()

    print(
        "\n".join(
            banner_lines(
                state, args.port, lan_ip, getattr(app, "load_reason", None), args.data_dir, alternates=candidates
            )
        )
    )
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
