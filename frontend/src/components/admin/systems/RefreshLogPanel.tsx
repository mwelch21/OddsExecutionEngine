import { EmptyState } from "../../primitives";
import { AdminPanel } from "../AdminPanel";

/** Every refresh, manual or Auto-Refresh, with its cost and outcome. Built in #103. */
export function RefreshLogPanel() {
  return (
    <AdminPanel title="Refresh log">
      <EmptyState>The refresh log is not built yet. Each refresh will show here.</EmptyState>
    </AdminPanel>
  );
}
