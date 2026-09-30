import type { ReactNode } from "react";
import type { Item } from "../types";

/** Shared loot-card chrome: tier-tinted card, name + tier chip, bonus,
 * flavor. Children are the per-view action buttons (claim / toss / assign). */
export function LootCardBody({
  item,
  className,
  children,
}: {
  item: Item;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div className={`loot-card tier-${item.tier}${className ? ` ${className}` : ""}`}>
      <div className="loot-head">
        <strong>{item.name}</strong>
        <span className={`tier tier-${item.tier}`}>{item.tier}</span>
      </div>
      {item.bonus && <div className="loot-bonus">{item.bonus}</div>}
      {item.description && <div className="loot-desc">{item.description}</div>}
      {children}
    </div>
  );
}
