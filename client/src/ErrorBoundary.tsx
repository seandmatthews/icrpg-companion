import { Component, type ReactNode } from "react";

interface State {
  crashed: boolean;
}

/**
 * The client shell's floor (ticket 41): one thrown render error used to be a
 * bare white screen on a phone, mid-session. This renders a reload card
 * instead. Window-level errors and unhandled rejections get the same banner
 * (see installCrashHandlers below) — nothing fails silently.
 */
// set when the boundary fired, so the window-level handlers don't double-show
// the card in dev builds (React replays caught errors to window listeners)
let boundaryCrashed = false;

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { crashed: false };

  static getDerivedStateFromError(): State {
    boundaryCrashed = true;
    return { crashed: true };
  }

  componentDidCatch(error: unknown) {
    console.error("tc: render crashed", error);
  }

  render() {
    if (this.state.crashed) return <CrashCard />;
    return this.props.children;
  }
}

export function CrashCard() {
  return (
    <div className="screen-center">
      <div className="card key-card">
        <h2>Something broke</h2>
        <p className="hint">The table app hit an error it couldn't recover from.</p>
        <button className="btn btn-go" onClick={() => location.reload()}>
          Tap to reload
        </button>
      </div>
    </div>
  );
}

/**
 * Outside-React failures (async throws, unhandled rejections) can't trip the
 * boundary — surface them with the same card, imperatively.
 */
export function installCrashHandlers() {
  const show = (what: string, detail?: unknown) => {
    console.error(`tc: ${what}`, detail ?? "");
    if (boundaryCrashed || document.getElementById("tc-crash")) return;
    const host = document.createElement("div");
    host.id = "tc-crash";
    host.style.cssText = "position:fixed;inset:auto 0 0 0;z-index:9999";
    document.body.appendChild(host);
    const root = document.createElement("div");
    host.appendChild(root);
    import("react-dom/client").then(({ createRoot }) => {
      createRoot(root).render(<CrashCard />);
    });
  };
  window.addEventListener("error", (e) => {
    if (e.error) show("uncaught error", e.error);
  });
  window.addEventListener("unhandledrejection", (e) => {
    show("unhandled rejection", e.reason);
    e.preventDefault();
  });
}
