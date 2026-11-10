import type { ReactNode } from "react";
import { CollapseToggle, Panel, useCollapsed } from "../primitives";

/**
 * One titled, collapsible panel on an Admin view tab. `actions` sits beside the
 * title and stays visible while the panel is collapsed.
 */
export function AdminPanel({
  title,
  actions,
  children
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const [collapsed, toggle] = useCollapsed(`admin.${title}`);
  return (
    <Panel className={`admin-panel${collapsed ? " is-collapsed" : ""}`}>
      <div className="admin-panel-heading">
        <h2>{title}</h2>
        <div className="section-actions">
          {actions}
          <CollapseToggle collapsed={collapsed} onToggle={toggle} label={title} />
        </div>
      </div>
      {!collapsed && children}
    </Panel>
  );
}
