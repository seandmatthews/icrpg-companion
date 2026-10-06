import { useCallback, useEffect, useState } from "react";
import QRCode from "qrcode";
import type { ActiveView, Bootstrap } from "../types";
import type { RoomConn } from "../net";
import { useNow, useWakeLock } from "../util";
import { HeartStepper } from "../components/Hearts";
import { LootCardBody } from "../components/LootCard";
import { TNCard } from "../components/TNCard";
import { TimerGM } from "../components/Timers";

const TIERS = ["common", "uncommon", "rare", "epic"];

function Card({ title, children, className }: { title?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`card ${className ?? ""}`}>
      {title && <h2 className="card-title">{title}</h2>}
      {children}
    </section>
  );
}

function QRModal({ url, roomCode, onClose }: { url: string; roomCode: string; onClose: () => void }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    QRCode.toDataURL(url, { width: 512, margin: 2, color: { dark: "#16161a", light: "#f5f0e6" } }).then(setSrc);
  }, [url]);
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal qr-modal" onClick={(e) => e.stopPropagation()}>
        <h2>Seat the players</h2>
        {src ? <img src={src} alt="join QR code" className="qr-img" /> : <p>generating…</p>}
        <p className="qr-url">{url}</p>
        <p className="qr-room">
          room code <strong>{roomCode}</strong>
        </p>
        <p className="hint">Players scan, knock, and you seat them. GM approves every join.</p>
        <button className="btn" onClick={onClose}>
          Done
        </button>
      </div>
    </div>
  );
}

function AddTimerForm({ send, version }: { send: RoomConn["send"]; version: number }) {
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState<"alarm" | "rounds">("alarm");
  const [minutes, setMinutes] = useState(10);
  const [rounds, setRounds] = useState(5);
  const [sentAt, setSentAt] = useState<number | null>(null);
  // fields clear on the SUCCESS echo — a dropped send keeps the typed label
  useEffect(() => {
    if (sentAt != null && version !== sentAt) {
      setLabel("");
      setSentAt(null);
    }
  }, [version, sentAt]);
  const mins = Math.round(minutes);
  const r = Math.round(rounds);
  const valid = !!label.trim() && (kind === "alarm" ? mins >= 1 && mins <= 1440 : r >= 1 && r <= 99);
  const add = () => {
    if (!valid) return;
    if (kind === "alarm") send("timer_add", { label, kind, duration_s: mins * 60 });
    else send("timer_add", { label, kind, rounds: r });
    setSentAt(version);  // clear on echo
  };
  return (
    <div className="form-row">
      <input placeholder="timer name" value={label} onChange={(e) => setLabel(e.target.value)} />
      <select value={kind} onChange={(e) => setKind(e.target.value as "alarm" | "rounds")}>
        <option value="alarm">alarm clock</option>
        <option value="rounds">room timer</option>
      </select>
      {kind === "alarm" ? (
        <input type="number" min={1} max={1440} value={minutes} onChange={(e) => setMinutes(+e.target.value)} title="minutes" />
      ) : (
        <input type="number" min={1} max={99} value={rounds} onChange={(e) => setRounds(+e.target.value)} title="rounds" />
      )}
      <button className="btn" onClick={add} disabled={!valid}>
        Add
      </button>
    </div>
  );
}

function AddLootForm({ send, version }: { send: RoomConn["send"]; version: number }) {
  const [name, setName] = useState("");
  const [tier, setTier] = useState("common");
  const [bonus, setBonus] = useState("");
  const [desc, setDesc] = useState("");
  const [sentAt, setSentAt] = useState<number | null>(null);
  useEffect(() => {
    if (sentAt != null && version !== sentAt) {
      setName("");
      setBonus("");
      setDesc("");
      setSentAt(null);
    }
  }, [version, sentAt]);
  const add = () => {
    if (!name.trim()) return;
    send("loot_add", { name, tier, bonus, description: desc });
    setSentAt(version);  // clear on echo
  };
  return (
    <div className="loot-form">
      <div className="form-row">
        <input placeholder="item name" value={name} onChange={(e) => setName(e.target.value)} />
        <select value={tier} onChange={(e) => setTier(e.target.value)}>
          {TIERS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>
      <div className="form-row">
        <input placeholder="bonus (+1 CHA…)" value={bonus} onChange={(e) => setBonus(e.target.value)} />
        <input placeholder="flavor text" value={desc} onChange={(e) => setDesc(e.target.value)} />
        <button className="btn" onClick={add} disabled={!name.trim()}>
          Add
        </button>
      </div>
    </div>
  );
}

function AddNpcForm({ send, version }: { send: RoomConn["send"]; version: number }) {
  const [name, setName] = useState("");
  const [hearts, setHearts] = useState("1");
  const [die, setDie] = useState("d6");
  const [abilities, setAbilities] = useState("");
  const [sentAt, setSentAt] = useState<number | null>(null);
  useEffect(() => {
    if (sentAt != null && version !== sentAt) {
      setName("");
      setAbilities("");
      setSentAt(null);
    }
  }, [version, sentAt]);
  const h = parseFloat(hearts);
  const valid = !!name.trim() && h >= 0.5 && h <= 40 && h * 2 === Math.round(h * 2);
  const add = () => {
    if (!valid) return;
    send("npc_add", {
      name,
      hearts_max: h,
      effort_die: die,
      abilities: abilities.split(",").map((a) => a.trim()).filter(Boolean),
      visible: false,
    });
    setSentAt(version);  // clear on echo
  };
  return (
    <div className="form-row">
      <input placeholder="npc name" value={name} onChange={(e) => setName(e.target.value)} />
      <input type="number" min={0.5} step={0.5} max={40} value={hearts} onChange={(e) => setHearts(e.target.value)} title="hearts" />
      <select value={die} onChange={(e) => setDie(e.target.value)}>
        {["d4", "d6", "d8", "d10", "d12"].map((d) => (
          <option key={d}>{d}</option>
        ))}
      </select>
      <input placeholder="abilities, comma…" value={abilities} onChange={(e) => setAbilities(e.target.value)} />
      <button className="btn" onClick={add} disabled={!valid}>
        Add
      </button>
    </div>
  );
}

function exportReport(v: ActiveView) {
  const loot = v.loot ?? [];
  const party = v.party ?? [];
  const nameOf = (pcId: string | null) => party.find((p) => p.pc_id === pcId)?.name ?? null;
  const report = {
    schema: "session-report/v0.1",
    campaign: null,
    session_id: v.session_id,
    played_on: new Date().toISOString().slice(0, 10),
    loot_claimed: loot.filter((i) => i.claimed_by).map((i) => ({ item_id: i.item_id, name: i.name, pc_id: i.claimed_by, pc_name: nameOf(i.claimed_by) })),
    milestones: v.milestones ?? [],
    notable_events: (v.log ?? []).filter((e) => e.audience === "all").map((e) => ({ actor: e.actor, text: e.text, ts: e.ts })),
    session_summary: "",
  };
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `session-report-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function GMView({ conn, bootstrap }: { conn: RoomConn<"gm">; bootstrap: Bootstrap | null }) {
  const { view, send } = conn;
  const now = useNow(500);
  useWakeLock(true);
  const [showQR, setShowQR] = useState(false);
  const [note, setNote] = useState("");
  const [shareNote, setShareNote] = useState(false);
  const [titleDraft, setTitleDraft] = useState<string | null>(null);

  // in-flight latch: a send inside the echo window is ignored, so a
  // double-tap can't raise spurious "already …" toasts or duplicate loads
  // (ticket 50). Cleared by the next commit (version) or the next error.
  const version = view?.version ?? 0;
  const errTs = conn.error?.ts ?? 0;
  const [busy, setBusy] = useState(false);
  useEffect(() => setBusy(false), [view, errTs]);  // any fresh state frame clears
  const gsend = useCallback(
    (action: string, args?: Record<string, unknown>) => {
      if (busy) return;
      setBusy(true);
      send(action, args);
    },
    [busy, send]
  );

  if (!view) {
    return <div className="screen-center">connecting to the table…</div>;
  }
  const party = view.party ?? [];
  const loot = view.loot ?? [];
  const boundIds = new Set(Object.values(view.bindings ?? {}).map((b: { pc_id: string }) => b.pc_id));
  const seatable = party.filter((p) => !boundIds.has(p.pc_id));

  const playersUrl = bootstrap?.lan_ip
    ? `${location.protocol}//${bootstrap.lan_ip}:${location.port}/join?room=${view.room_code}`
    : `${location.origin}/join?room=${view.room_code}`;

  return (
    <div className="gm-view">
      <header className="topbar">
        <input
          className="title-input"
          value={titleDraft ?? view.title}
          onChange={(e) => setTitleDraft(e.target.value)}
          onBlur={() => {
            if (titleDraft !== null && titleDraft !== view.title) gsend("set_title", { title: titleDraft });
            setTitleDraft(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          aria-label="session title"
        />
        <span className="room-chip">
          room <strong>{view.room_code}</strong>
        </span>
        <span className={`conn conn-${conn.status}`} title={conn.status} />
        <button className="btn btn-go" onClick={() => setShowQR(true)}>
          Show QR
        </button>
      </header>

      {(view.alarm ?? []).length > 0 && (
        <div className="alarm-banner">
          ⏰ {view.alarm![0].label} — TIME!
          {(view.alarm ?? []).length > 1 && <span> (+{(view.alarm ?? []).length - 1} more)</span>}
          <button className="btn" onClick={() => gsend("alarm_dismiss")}>
            Dismiss
          </button>
        </div>
      )}

      {(view.join_requests?.length ?? 0) > 0 && (
        <div className="knock-panel">
          {view.join_requests!.map((r) => (
            <div key={r.device_token} className="knock">
              <strong>{r.name}</strong> is knocking
              <select
                defaultValue=""
                onChange={(e) => {
                  if (e.target.value) gsend("approve_join", { device_token: r.device_token, pc_id: e.target.value });
                  e.target.value = "";
                }}
              >
                <option value="" disabled>
                  seat as…
                </option>
                {seatable.map((p) => (
                  <option key={p.pc_id} value={p.pc_id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <button className="btn btn-sm" onClick={() => gsend("reject_join", { device_token: r.device_token })}>
                Turn away
              </button>
            </div>
          ))}
        </div>
      )}

      {(view.rejections?.length ?? 0) > 0 && (
        <div className="knock-panel">
          {view.rejections!.map((r) => (
            <div key={r.device_token} className="knock">
              <strong>{r.name || "A turned-away player"}</strong> was turned away
              <select
                defaultValue=""
                onChange={(e) => {
                  if (e.target.value) gsend("approve_join", { device_token: r.device_token, pc_id: e.target.value });
                  e.target.value = "";
                }}
              >
                <option value="" disabled>
                  seat anyway…
                </option>
                {seatable.map((p) => (
                  <option key={p.pc_id} value={p.pc_id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
      )}

      <div className="gm-grid">
        <div className="gm-col">
          <Card title="Timers">
            <div className="timers-list">
              {view.timers.map((t) => (
                <TimerGM key={t.timer_id} timer={t} skew={conn.skew} now={now} send={gsend} busy={busy} />
              ))}
              {view.timers.length === 0 && <p className="hint">No timers yet. Alarm clocks count real time; room timers tick down per round.</p>}
            </div>
            <AddTimerForm send={gsend} version={version} />
          </Card>

          <Card title="The Ladder">
            <TNCard targets={view.targets} gm onDelta={(which, delta) => gsend("set_targets", { which, delta })} />
          </Card>

          <Card title="NPCs">
            <div className="npc-list">
              {(view.npcs ?? []).map((n) => (
                <div key={n.npc_id} className={`npc ${n.visible ? "npc-visible" : ""}`}>
                  <div className="npc-head">
                    <strong>{n.name}</strong>
                    <span className="npc-die">{n.effort_die}</span>
                    <button
                      className={`btn btn-sm ${n.visible ? "" : "btn-go"}`}
                      onClick={() => gsend("npc_reveal", { npc_id: n.npc_id, visible: !n.visible })}
                    >
                      {n.visible ? "on screen" : "reveal"}
                    </button>
                    <button className="btn btn-sm btn-ghost" onClick={() => gsend("npc_delete", { npc_id: n.npc_id })}>
                      ✕
                    </button>
                  </div>
                  <HeartStepper current={n.hearts} max={n.hearts_max} onDelta={(d) => gsend("npc_hearts", { npc_id: n.npc_id, delta: d })} />
                  {n.abilities.length > 0 && <div className="npc-abilities">{n.abilities.join(" · ")}</div>}
                </div>
              ))}
            </div>
            <AddNpcForm send={gsend} version={version} />
          </Card>

          <Card title="Table log">
            <div className="log-list">
              {(view.log ?? []).slice().reverse().map((e) => (
                <div key={e.id ?? e.ts} className={`log-entry ${e.audience === "gm" ? "log-gm" : ""}`}>
                  <span className="log-actor">{e.actor}</span> {e.text}
                </div>
              ))}
            </div>
            <div className="form-row">
              <input
                placeholder="dm note…"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && note.trim()) {
                    gsend("log_note", { text: note, share: shareNote });
                    setNote("");
                  }
                }}
              />
              <label className="check">
                <input type="checkbox" checked={shareNote} onChange={(e) => setShareNote(e.target.checked)} />
                players see it
              </label>
            </div>
          </Card>
        </div>

        <div className="gm-col">
          <Card title="Party">
            {party.length === 0 && <p className="hint">No characters yet — add one, or seat a player who knocks.</p>}
            <div className="party-list">
              {party.map((p) => (
                <div key={p.pc_id} className="pc">
                  <div className="pc-head">
                    <strong>{p.name}</strong>
                    {p.player_label && <span className="player-label">({p.player_label})</span>}
                    <button
                      className="btn btn-sm btn-ghost"
                      onClick={() => {
                        const reason = prompt(`Milestone for ${p.name}?`);
                        if (reason && reason.trim()) gsend("milestone_add", { pc_id: p.pc_id, reason });
                      }}
                    >
                      Milestone
                    </button>
                    <button
                      className="btn btn-sm btn-ghost"
                      onClick={() => {
                        if (confirm(`Remove ${p.name}?`)) gsend("pc_delete", { pc_id: p.pc_id });
                      }}
                    >
                      ✕
                    </button>
                  </div>
                  <HeartStepper current={p.hearts} max={p.hearts_max} onDelta={(d) => gsend("pc_hearts", { pc_id: p.pc_id, delta: d })} />
                  <div className="pc-inventory">
                    {loot.filter((i) => i.claimed_by === p.pc_id).map((i) => (
                      <span key={i.item_id} className="chip" title={i.description}>
                        {i.name}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <AddPcForm send={gsend} version={version} />
          </Card>

          <Card title="Loot pool">
            <div className="loot-grid">
              {loot.map((i) => {
                const owner = party.find((p) => p.pc_id === i.claimed_by);
                return (
                  <LootCardBody key={i.item_id} item={i}>
                    <div className="loot-foot">
                      {owner ? (
                        <>
                          <span className="owner">→ {owner.name}</span>
                          <button className="btn btn-sm" onClick={() => gsend("loot_assign", { item_id: i.item_id, pc_id: null })}>
                            Recall
                          </button>
                        </>
                      ) : (
                        <select
                          defaultValue=""
                          onChange={(e) => {
                            if (e.target.value) gsend("loot_assign", { item_id: i.item_id, pc_id: e.target.value });
                            e.target.value = "";
                          }}
                        >
                          <option value="" disabled>
                            assign to…
                          </option>
                          {party.map((p) => (
                            <option key={p.pc_id} value={p.pc_id}>
                              {p.name}
                            </option>
                          ))}
                        </select>
                      )}
                      <button className="btn btn-sm btn-ghost" onClick={() => gsend("loot_delete", { item_id: i.item_id })}>
                        ✕
                      </button>
                    </div>
                  </LootCardBody>
                );
              })}
            </div>
            <AddLootForm send={gsend} version={version} />
            {loot.length === 0 && (
              <button className="btn" onClick={() => gsend("starter_load", { pack: "alfheim" })}>
                Load Alfheim starter kit
              </button>
            )}
          </Card>

          <Card title="Milestones">
            {(view.milestones ?? []).length === 0 && <p className="hint">None yet. Milestones are advancement earned at the table.</p>}
            <div className="milestone-list">
              {(view.milestones ?? []).map((m) => (
                <div key={m.id ?? `${m.pc_id}-${m.ts}`} className="milestone">
                  <strong>{m.pc_name}</strong> — {m.reason}
                  <button className="btn btn-sm btn-ghost" onClick={() => gsend("milestone_delete", { id: m.id })}>
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Session">
            <button className="btn" onClick={() => exportReport(view)}>
              Download session report
            </button>
            <button
              className="btn btn-danger"
              onClick={() => {
                if (confirm("Start a fresh session? Everything in this one is discarded (the snapshot too).")) {
                  gsend("session_reset");
                }
              }}
            >
              New session
            </button>
          </Card>
        </div>
      </div>

      {showQR && <QRModal url={playersUrl} roomCode={view.room_code} onClose={() => setShowQR(false)} />}
      {conn.error && (
        <div key={conn.error.ts} className="toast">
          {conn.error.message}
        </div>
      )}
    </div>
  );
}

function AddPcForm({ send, version }: { send: RoomConn["send"]; version: number }) {
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [hearts, setHearts] = useState(3);
  const [sentAt, setSentAt] = useState<number | null>(null);
  useEffect(() => {
    if (sentAt != null && version !== sentAt) {
      setName("");
      setLabel("");
      setSentAt(null);
    }
  }, [version, sentAt]);
  const valid = !!name.trim() && Number.isInteger(hearts) && hearts >= 1 && hearts <= 20;
  const add = () => {
    if (!valid) return;
    send("pc_add", { name, player_label: label, hearts_max: hearts });
    setSentAt(version);  // clear on echo
  };
  return (
    <div className="form-row">
      <input placeholder="character name" value={name} onChange={(e) => setName(e.target.value)} />
      <input placeholder="player (optional)" value={label} onChange={(e) => setLabel(e.target.value)} />
      <input type="number" min={1} max={20} value={hearts} onChange={(e) => setHearts(+e.target.value)} title="hearts" />
      <button className="btn" onClick={add} disabled={!valid}>
        Add
      </button>
    </div>
  );
}
