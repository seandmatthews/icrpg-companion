import type { Timer } from "../types";
import { fmtClock, timerRemainSec } from "../util";

function Countdown({ timer, skew, now }: { timer: Timer; skew: number; now: number }) {
  const remain = timerRemainSec(timer, skew, now);
  if (timer.kind === "rounds") {
    const left = timer.rounds_left ?? 0;
    return (
      <span className={`rounds ${left === 0 ? "rounds-zero" : ""}`}>
        {"●".repeat(Math.min(left, 10))}
        <span className="rounds-num">{left} rounds</span>
      </span>
    );
  }
  if (remain == null) {
    return <span className="countdown countdown-idle">{fmtClock(timer.duration_s ?? 0)}</span>;
  }
  const cls = remain > 0 && remain <= 30 ? "countdown countdown-hot" : "countdown";
  return <span className={cls}>{fmtClock(remain)}</span>;
}

export function TimerStatus({ timer, skew, now }: { timer: Timer; skew: number; now: number }) {
  const remain = timerRemainSec(timer, skew, now);
  const urgent = remain != null && remain <= 30 && remain > 0;
  return (
    <div className={`timer ${urgent ? "timer-hot" : ""} ${timer.status === "done" ? "timer-done" : ""}`}>
      <div className="timer-label">{timer.label}</div>
      <Countdown timer={timer} skew={skew} now={now} />
      {timer.status !== "idle" && (
        <span className={`timer-state state-${timer.status}`}>{timer.status}</span>
      )}
    </div>
  );
}

export function TimerGM({
  timer,
  skew,
  now,
  send,
  busy = false,
}: {
  timer: Timer;
  skew: number;
  now: number;
  send: (action: string, args?: Record<string, unknown>) => void;
  busy?: boolean;
}) {
  const id = { timer_id: timer.timer_id };
  return (
    <div className={`timer ${timer.status === "done" ? "timer-done" : ""}`}>
      <div className="timer-head">
        <span className="timer-label">{timer.label}</span>
        <button className="btn btn-sm btn-ghost" onClick={() => send("timer_delete", id)} title="delete timer">
          ✕
        </button>
      </div>
      <div className="timer-body">
        <Countdown timer={timer} skew={skew} now={now} />
        <span className={`timer-state state-${timer.status}`}>{timer.status}</span>
      </div>
      <div className="timer-controls">
        {timer.kind === "alarm" ? (
          <>
            {timer.status === "running" ? (
              <button className="btn" onClick={() => send("timer_pause", id)}>
                Pause
              </button>
            ) : (
              <button className="btn btn-go" onClick={() => send("timer_start", id)}>
                {timer.status === "paused" ? "Resume" : "Start"}
              </button>
            )}
          </>
        ) : (
          <button
            className="btn btn-go"
            disabled={busy || (timer.rounds_left ?? 0) <= 0}
            onClick={() => send("timer_tick", id)}
          >
            Tick round
          </button>
        )}
        <button className="btn" onClick={() => send("timer_reset", id)}>
          Reset
        </button>
      </div>
    </div>
  );
}
