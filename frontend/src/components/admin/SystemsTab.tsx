import { DeliveryLogPanel } from "./systems/DeliveryLogPanel";
import { RefreshLogPanel } from "./systems/RefreshLogPanel";

/**
 * Whether the system is working (#95 Variant A). Each panel is its own file, so
 * the refresh log (#103) and delivery log (#105) land without touching this one.
 */
export function SystemsTab() {
  return (
    <div className="admin-two">
      <RefreshLogPanel />
      <DeliveryLogPanel />
    </div>
  );
}
