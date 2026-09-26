export function TNCard({
  targets,
  gm,
  onDelta,
}: {
  targets: { default: number; scene: number };
  gm?: boolean;
  onDelta?: (which: "default" | "scene", delta: number) => void;
}) {
  return (
    <div className="tn-card">
      <div className="tn-item">
        <div className="tn-label">TARGET</div>
        <div className="tn-num">
          {gm && onDelta && (
            <button className="btn btn-sm" onClick={() => onDelta("default", -1)}>
              −
            </button>
          )}
          <span>{targets.default}</span>
          {gm && onDelta && (
            <button className="btn btn-sm" onClick={() => onDelta("default", 1)}>
              +
            </button>
          )}
        </div>
      </div>
      <div className="tn-divider" />
      <div className="tn-item">
        <div className="tn-label">SCENE</div>
        <div className="tn-num">
          {gm && onDelta && (
            <button className="btn btn-sm" onClick={() => onDelta("scene", -1)}>
              −
            </button>
          )}
          <span>{targets.scene}</span>
          {gm && onDelta && (
            <button className="btn btn-sm" onClick={() => onDelta("scene", 1)}>
              +
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
