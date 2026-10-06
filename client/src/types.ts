// Mirror of the server's state shapes (server/state.py). Views are
// role-filtered server-side, so everything here is optional where a
// filtered view may omit it.

export interface Timer {
  timer_id: string;
  label: string;
  kind: "alarm" | "rounds";
  duration_s: number | null;
  rounds_total: number | null;
  rounds_left: number | null;
  started_at: number | null;
  elapsed_before_pause: number;
  status: "idle" | "running" | "paused" | "done";
}

export interface Item {
  item_id: string;
  name: string;
  tier: "common" | "uncommon" | "rare" | "epic";
  bonus: string;
  description: string;
  claimed_by: string | null;
}

export interface PC {
  pc_id: string;
  name: string;
  player_label: string;
  hearts_max: number;
  hearts: number;
}

export interface NPC {
  npc_id: string;
  name: string;
  hearts_max: number;
  hearts: number;
  effort_die: string;
  abilities: string[];
  visible: boolean;
}

export interface JoinRequest {
  device_token: string;
  name: string;
}

export interface LogEntry {
  ts: string;
  audience: "all" | "gm";
  actor: string;
  text: string;
}

export interface Milestone {
  pc_id: string;
  pc_name?: string;
  reason: string;
  ts: string;
}

// The pending view omits every full-view collection, so StateView is a
// discriminated union on `status`: narrowing on status === "pending" gives
// the compiler permission to touch only the pending fields (ticket 33).
export interface PendingView {
  schema: string;
  version: number;
  room_code: string;
  title: string;
  status: "pending";
  rejected?: true;
  party: { pc_id: string; name: string; player_label: string }[];
}

export interface ActiveView {
  schema: string;
  version: number;
  room_code: string;
  session_id?: string;
  title: string;
  targets: { default: number; scene: number };
  timers: Timer[];
  party?: PC[];
  npcs?: NPC[];
  loot?: Item[];
  join_requests?: JoinRequest[];
  rejections?: JoinRequest[];
  bindings?: Record<string, { pc_id: string }>;
  log?: LogEntry[];
  milestones?: Milestone[];
  alarm: { timer_id: string; label: string } | null;
  you?: { pc_id: string };
  status?: undefined;
}

export type StateView = PendingView | ActiveView;

export interface Bootstrap {
  room_code: string;
  session_id: string;
  title: string;
  version: number;
  server_time: number;
  lan_ip: string | null;
}
