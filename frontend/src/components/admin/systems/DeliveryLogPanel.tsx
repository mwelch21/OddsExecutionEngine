import { EmptyState } from "../../primitives";
import { AdminPanel } from "../AdminPanel";

/** Every notification delivery, failures included. Built in #105. */
export function DeliveryLogPanel() {
  return (
    <AdminPanel title="Delivery log">
      <EmptyState>The delivery log is not built yet. Each notification will show here.</EmptyState>
    </AdminPanel>
  );
}
