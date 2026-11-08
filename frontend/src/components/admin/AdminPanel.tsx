import type { ReactNode } from "react";
import { Panel } from "../primitives";

/** One titled panel on an Admin view tab. `actions` sits beside the title. */
export function AdminPanel({
  title,
  actions,
  children
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Panel className="admin-panel">
      <div className="admin-panel-heading">
        <h2>{title}</h2>
        {actions}
      </div>
      {children}
    </Panel>
  );
}
