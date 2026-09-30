import { useEffect, useState } from "react";
import type { Bootstrap } from "./types";
import { getGmKey, getSeat, setGmKey, setSeat, clearCachedView, type Seat } from "./util";
import { useRoom } from "./net";
import { GMView } from "./views/GMView";
import { PlayerView } from "./views/PlayerView";

/** Public bootstrap: room code + LAN IP for the QR, plus server clock. */
function useBootstrap(): Bootstrap | null {
  const [b, setB] = useState<Bootstrap | null>(null);
  useEffect(() => {
    fetch("/api/bootstrap")
      .then((r) => r.json())
      .then(setB)
      .catch(() => {});
  }, []);
  return b;
}

// ---------------------------------------------------------------------------

function GMKeyForm({ onKey }: { onKey: (k: string) => void }) {
  const [keyInput, setKeyInput] = useState("");
  return (
    <div className="screen-center">
      <div className="card key-card">
        <h2>GM console</h2>
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

function GMConnected({ gmKey }: { gmKey: string }) {
  const bootstrap = useBootstrap();
  const conn = useRoom("gm", {
    gmKey,
    onAuthFail: () => {
      setGmKey(null);
      clearCachedView();
    },
  });
  if (conn.status === "connecting" && !conn.view) return <div className="screen-center">connecting…</div>;
  return <GMView conn={conn} bootstrap={bootstrap} />;
}

function GMFlow() {
  const [key, setKey] = useState<string | null>(getGmKey());
  if (!key) return <GMKeyForm onKey={(k) => { setGmKey(k); setKey(k); }} />;
  return <GMConnected key={key} gmKey={key} />;
}

// ---------------------------------------------------------------------------

function JoinForm({ bootstrap, onSeat }: { bootstrap: Bootstrap | null; onSeat: (s: Seat) => void }) {
  const [roomInput, setRoomInput] = useState(new URLSearchParams(location.search).get("room") ?? "");
  const [nameInput, setNameInput] = useState("");
  return (
    <div className="screen-center">
      <div className="card key-card">
        <h2>Join the table</h2>
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

function PlayerConnected({ seat }: { seat: Seat }) {
  const conn = useRoom("player", {
    room: seat.room,
    name: seat.name,
    onAuthFail: () => {
      setSeat(null);
      clearCachedView();
    },
  });
  if (conn.status === "connecting" && !conn.view) return <div className="screen-center">knocking…</div>;
  return <PlayerView conn={conn} />;
}

function PlayerFlow({ initialSeat }: { initialSeat: Seat | null }) {
  const bootstrap = useBootstrap();
  const [seat, setSeatState] = useState<Seat | null>(initialSeat);
  if (!seat) return <JoinForm bootstrap={bootstrap} onSeat={(s) => { setSeat(s); setSeatState(s); }} />;
  return <PlayerConnected key={seat.room + seat.name} seat={seat} />;
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
