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
  const cells: ("full" | "half" | "empty")[] = [];
  for (let i = 0; i < max; i++) {
    if (i < whole) cells.push("full");
    else if (i === whole && half) cells.push("half");
    else cells.push("empty");
  }
  return (
    <span className={`hearts ${size === "lg" ? "hearts-lg" : ""}`} title={`${current}/${max}`}>
      {cells.map((f, i) => (
        <Heart key={i} fill={f} />
      ))}
      {max > 20 && <span className="hearts-overflow">({filled}/{max})</span>}
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
