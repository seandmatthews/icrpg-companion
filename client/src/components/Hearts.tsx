function Heart({ fill }: { fill: "full" | "half" | "empty" }) {
  if (fill === "half") {
    return (
      <span className="heart">
        <span className="heart-empty">♥</span>
        <span className="heart-full heart-half-clip">♥</span>
      </span>
    );
  }
  return fill === "full" ? <span className="heart heart-full">♥</span> : <span className="heart heart-empty">♥</span>;
}

export function Hearts({ current, max, size }: { current: number; max: number; size?: "lg" }) {
  const whole = Math.floor(current);
  const half = current - whole >= 0.25 && current - whole < 0.75 ? 1 : 0;
  const filled = Math.round(current);
  // above 12 cells the row overflows a 375px phone — switch to a big honest
  // numeric readout instead of an unreadable heart strip (ticket 51)
  if (max > 12) {
    return (
      <span className={`hearts hearts-numeric ${size === "lg" ? "hearts-lg" : ""}`} title={`${current}/${max}`}>
        <span className="heart heart-full">♥</span>
        <span className="hearts-count">
          {Number.isInteger(current) ? filled : current}/{max}
        </span>
      </span>
    );
  }
  const cells: ("full" | "half" | "empty")[] = [];
  for (let i = 0; i < max; i++) {
    if (i < whole) cells.push("full");
    else if (i === whole && half) cells.push("half");
    else cells.push("empty");
  }
  return (
    <span
      className={`hearts ${size === "lg" ? "hearts-lg" : ""} ${max > 9 ? "hearts-many" : ""}`}
      title={`${current}/${max}`}
    >
      {cells.map((f, i) => (
        <Heart key={i} fill={f} />
      ))}
    </span>
  );
}

export function HeartStepper({
  current,
  max,
  onDelta,
}: {
  current: number;
  max: number;
  onDelta: (delta: number) => void;
}) {
  return (
    <span className="heart-stepper">
      <button className="btn btn-sm" onClick={() => onDelta(-1)} aria-label="damage">
        −
      </button>
      <Hearts current={current} max={max} size="lg" />
      <button className="btn btn-sm" onClick={() => onDelta(1)} aria-label="heal">
        +
      </button>
    </span>
  );
}
