import { EmptyState } from "../primitives";
import { AdminPanel } from "./AdminPanel";

/** What the system costs: balance, history, burn per sport. Built in #104. */
export function CreditsTab() {
  return (
    <AdminPanel title="Credits">
      <EmptyState>
        The Credits tab is not built yet. It will show credits left, their history and
        the burn per sport.
      </EmptyState>
    </AdminPanel>
  );
}
