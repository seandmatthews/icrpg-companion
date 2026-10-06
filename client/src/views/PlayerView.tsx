import { useState } from "react";
import type { Item } from "../types";
import type { RoomConn } from "../net";
import { useNow, useWakeLock } from "../util";
import { HeartStepper } from "../components/Hearts";
import { LootCardBody } from "../components/LootCard";
import { TNCard } from "../components/TNCard";
import { TimerStatus } from "../components/Timers";

function PoolCard({ item, onClaim }: { item: Item; onClaim: (item: Item) => void }) {
  const [claiming, setClaiming] = useState(false);
  return (
    <LootCardBody item={item} className={claiming ? "claiming" : undefined}>
      <button
        className="btn btn-go btn-claim"
        onClick={() => {
          setClaiming(true);
          onClaim(item);
        }}
      >
        Claim
      </button>
    </LootCardBody>
  );
}

function AlarmOverlay({ label, onQuiet }: { label: string; onQuiet: () => void }) {
  return (
    <div className="alarm-overlay" onClick={onQuiet}>
      <div className="alarm-text">⏰</div>
      <div className="alarm-text">{label}</div>
      <div className="alarm-text alarm-big">TIME!</div>
      <div className="hint">tap to hush — the GM resets the clock</div>
    </div>
  );
}

export function PlayerView({ conn }: { conn: RoomConn }) {
  const { view, send } = conn;
  const now = useNow(500);
  useWakeLock(true);
  const [hushed, setHushed] = useState<string | null>(null);

  if (!view) return <div className="screen-center">connecting to the table…</div>;
  if (view.status === "pending") {
    if (view.rejected) {
      return (
        <div className="screen-center pending-screen">
          <div className="card pending-card">
            <h2>Turned away</h2>
            <p>The GM turned you away from room <strong>{view.room_code}</strong>.</p>
            <p className="hint">You can close this page — the GM can seat you again if you should return.</p>
          </div>
        </div>
      );
    }
    return (
      <div className="screen-center pending-screen">
        <div className="card pending-card">
          <h2>Knock knock…</h2>
          <p>You're at the door of room <strong>{view.room_code}</strong>.</p>
          <p className="hint">Waiting for the GM to wave you in.</p>
        </div>
      </div>
    );
  }

  const me = (view.party ?? []).find((p) => p.pc_id === view.you?.pc_id);
  if (!me) return <div className="screen-center">your seat vanished — ask the GM for a new one</div>;

  const loot = view.loot ?? [];
  const mine = loot.filter((i) => i.claimed_by === me.pc_id);
  const pool = loot.filter((i) => i.claimed_by === null);
  // the alarm slot is a queue — show the first ring this player hasn't hushed
  const ringing = (view.alarm ?? []).find((a) => a.timer_id !== hushed);

  return (
    <div className="player-view">
      {ringing && <AlarmOverlay label={ringing.label} onQuiet={() => setHushed(ringing.timer_id)} />}

      <div className="tn-mini">
        <TNCard targets={view.targets} />
      </div>

      <header className="player-header">
        <div>
          <h1 className="pc-name">{me.name}</h1>
          {me.player_label && <div className="player-label">{me.player_label}</div>}
        </div>
        <span className={`conn conn-${conn.status}`} title={conn.status} />
      </header>

      <section className="card player-hearts">
        <h2 className="card-title">Hearts</h2>
        <HeartStepper current={me.hearts} max={me.hearts_max} onDelta={(d) => send("player_hearts", { delta: d })} />
      </section>

      <section className="card">
        <h2 className="card-title">Timers</h2>
        <div className="timers-list">
          {view.timers.map((t) => (
            <TimerStatus key={t.timer_id} timer={t} skew={conn.skew} now={now} />
          ))}
          {view.timers.length === 0 && <p className="hint">No timers running.</p>}
        </div>
      </section>

      <section className="card">
        <h2 className="card-title">Your pack</h2>
        <div className="loot-grid">
          {mine.map((i) => (
            <LootCardBody key={i.item_id} item={i} className="loot-enter">
              <button className="btn btn-sm" onClick={() => send("player_return", { item_id: i.item_id })}>
                Toss back
              </button>
            </LootCardBody>
          ))}
          {mine.length === 0 && <p className="hint">Nothing yet — grab something from the pool below.</p>}
        </div>
      </section>

      <section className="card">
        <h2 className="card-title">Loot pool</h2>
        <div className="loot-grid">
          {pool.map((i) => (
            <PoolCard key={i.item_id} item={i} onClaim={(item) => send("player_claim", { item_id: item.item_id })} />
          ))}
          {pool.length === 0 && <p className="hint">The pool is empty.</p>}
        </div>
      </section>

      <footer className="player-footer">
        <span className="room-chip">
          room <strong>{view.room_code}</strong>
        </span>
        <span className="hint">{view.title}</span>
      </footer>

      {conn.error && (
        <div key={conn.error.ts} className="toast">
          {conn.error.message}
        </div>
      )}
    </div>
  );
}
