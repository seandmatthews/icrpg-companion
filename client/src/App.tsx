import { useEffect, useState } from "react";
import type { Bootstrap } from "./types";
import { getGmKey, getSeat, setGmKey, setSeat, clearCachedView, type Seat } from "./util";
import { useRoom } from "./net";
import { GMView } from "./views/GMView";
import { PlayerView } from "./views/PlayerView";

/**
 * Public bootstrap: room code + LAN IP for the QR, plus server clock.
 * Ticket 40: a 500-body or a hung request must not be mistaken for success —
 * the QR modal shows "generating…" until a real bootstrap lands and an
 * explicit failure instead of silently encoding localhost.
 */
interface BootstrapState {
  b: Bootstrap | null;
  failed: boolean;
}

function useBootstrap(): BootstrapState {
  const [state, setState] = useState<BootstrapState>({ b: null, failed: false });
  useEffect(() => {
    const ctrl = new AbortController();
    const timeout = window.setTimeout(() => ctrl.abort(), 5000);
    fetch("/api/bootstrap", { signal: ctrl.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`bootstrap ${r.status}`);
        return r.json();
      })
      .then((b: Bootstrap) => {
        if (b && typeof b.room_code === "string" && typeof b.lan_ip !== "undefined") {
          setState({ b, failed: false });
        } else {
          setState({ b: null, failed: true });
        }
      })
      .catch(() => {
        setState({ b: null, failed: true });
      });
    return () => {
      window.clearTimeout(timeout);
      ctrl.abort();
    };
  }, []);
  return state;
}

// ---------------------------------------------------------------------------

function GMKeyForm({ error, onKey }: { error: string | null; onKey: (k: string) => void }) {
  const [keyInput, setKeyInput] = useState("");
  return (
    <div className="screen-center">
      <div className="card key-card">
        <h2>GM console</h2>
        {error && (
          <p className="hint" style={{ color: "var(--red-hot)" }}>
            {error}
          </p>
        )}
        <p className="hint">Paste the GM key printed by the server.</p>
        <div className="form-row">
          <input
            autoFocus
            placeholder="gm key"
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && keyInput.trim()) onKey(keyInput.trim());
            }}
          />
          <button className="btn btn-go" onClick={() => keyInput.trim() && onKey(keyInput.trim())}>
            Open
          </button>
        </div>
      </div>
    </div>
  );
}

function GMConnected({
  gmKey,
  onAuthFail,
}: {
  gmKey: string;
  onAuthFail: (message: string) => void;
}) {
  const { b, failed } = useBootstrap();
  const conn = useRoom("gm", {
    gmKey,
    onAuthFail: (message) => {
      setGmKey(null);
      clearCachedView();
      onAuthFail(message); // back to the key form, with the reason (ticket 40)
    },
  });
  if (!conn.view) {
    if (conn.status === "closed") {
      return (
        <div className="screen-center">
          <div className="card key-card">
            <h2>Can't reach the table</h2>
            <p className="hint">The server isn't answering — is `python run.py` still running?</p>
            <button
              className="btn"
              onClick={() => {
                setGmKey(null);
                clearCachedView();
                onAuthFail("server unreachable");
              }}
            >
              Back to the key form
            </button>
          </div>
        </div>
      );
    }
    return <div className="screen-center">connecting…</div>;
  }
  return <GMView conn={conn} bootstrap={b} bootstrapFailed={failed} />;
}

function GMFlow() {
  const [key, setKey] = useState<string | null>(getGmKey());
  const [authError, setAuthError] = useState<string | null>(null);
  if (!key)
    return (
      <GMKeyForm
        error={authError}
        onKey={(k) => {
          setGmKey(k);
          setAuthError(null);
          setKey(k);
        }}
      />
    );
  return (
    <GMConnected
      key={key}
      gmKey={key}
      onAuthFail={(m) => {
        setKey(null);
        setAuthError(m);
      }}
    />
  );
}

// ---------------------------------------------------------------------------

function JoinForm({
  bootstrap,
  bootstrapFailed,
  error,
  onSeat,
}: {
  bootstrap: Bootstrap | null;
  bootstrapFailed: boolean;
  error: string | null;
  onSeat: (s: Seat) => void;
}) {
  const [roomInput, setRoomInput] = useState(new URLSearchParams(location.search).get("room") ?? "");
  const [nameInput, setNameInput] = useState("");
  return (
    <div className="screen-center">
      <div className="card key-card">
        <h2>Join the table</h2>
        {error && (
          <p className="hint" style={{ color: "var(--red-hot)" }}>
            {error}
          </p>
        )}
        {bootstrapFailed && <p className="hint">can't reach the table server — check the room code by hand</p>}
        {bootstrap && <p className="hint">table room: {bootstrap.room_code}</p>}
        <div className="form-row">
          <input placeholder="room code" value={roomInput} onChange={(e) => setRoomInput(e.target.value.toUpperCase())} maxLength={6} />
        </div>
        <div className="form-row">
          <input placeholder="your name" value={nameInput} onChange={(e) => setNameInput(e.target.value)} />
          <button
            className="btn btn-go"
            disabled={!roomInput.trim() || !nameInput.trim()}
            onClick={() => onSeat({ room: roomInput.trim().toUpperCase(), name: nameInput.trim() })}
          >
            Knock
          </button>
        </div>
      </div>
    </div>
  );
}

function PlayerConnected({
  seat,
  onAuthFail,
}: {
  seat: Seat;
  onAuthFail: (message: string) => void;
}) {
  const conn = useRoom("player", {
    room: seat.room,
    name: seat.name,
    onAuthFail: (message) => {
      setSeat(null);
      clearCachedView();
      onAuthFail(message); // back to the join form, with the reason (ticket 40)
    },
  });
  if (!conn.view) {
    if (conn.status === "closed") {
      return (
        <div className="screen-center">
          <div className="card key-card">
            <h2>Can't reach the table</h2>
            <p className="hint">The server isn't answering — ask the GM to check the laptop.</p>
            <button
              className="btn"
              onClick={() => {
                setSeat(null);
                clearCachedView();
                onAuthFail("server unreachable");
              }}
            >
              Back to the join form
            </button>
          </div>
        </div>
      );
    }
    return <div className="screen-center">knocking…</div>;
  }
  return <PlayerView conn={conn} />;
}

function PlayerFlow({ initialSeat }: { initialSeat: Seat | null }) {
  const { b, failed } = useBootstrap();
  const [seat, setSeatState] = useState<Seat | null>(initialSeat);
  const [authError, setAuthError] = useState<string | null>(null);
  if (!seat)
    return (
      <JoinForm
        bootstrap={b}
        bootstrapFailed={failed}
        error={authError}
        onSeat={(s) => {
          setSeat(s);
          setAuthError(null);
          setSeatState(s);
        }}
      />
    );
  return (
    <PlayerConnected
      key={seat.room + seat.name}
      seat={seat}
      onAuthFail={(m) => {
        setSeatState(null);
        setAuthError(m);
      }}
    />
  );
}

// ---------------------------------------------------------------------------

function Landing({ onGM }: { onGM: () => void }) {
  return (
    <div className="screen-center">
      <div className="card key-card landing">
        <h1 className="brand">Table Companion</h1>
        <p className="hint">hearts · timers · loot — at the table, not in the way</p>
        <a className="btn btn-go" href="/join">
          I'm a player
        </a>
        <button className="btn" onClick={onGM}>
          I'm the GM
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const [gmFlow, setGmFlow] = useState(() => !!getGmKey());
  const seat = getSeat();
  if (location.pathname === "/join") return <PlayerFlow initialSeat={seat} />;
  if (gmFlow) return <GMFlow />;
  if (seat) return <PlayerFlow initialSeat={seat} />; // returning player reopened the PWA
  return <Landing onGM={() => setGmFlow(true)} />;
}
