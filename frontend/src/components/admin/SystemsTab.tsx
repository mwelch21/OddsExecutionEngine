import { ComponentStatusCards } from "./systems/ComponentStatusCards";
import { DeliveryLogPanel } from "./systems/DeliveryLogPanel";
import { MetricsPanel } from "./systems/MetricsPanel";
import { RefreshLogPanel } from "./systems/RefreshLogPanel";
import { useSystemStatus } from "./systems/systemStatus";

/**
 * Whether the system is working (#95 Variant A). Each panel is its own file, so
 * the refresh log (#103) and delivery log (#105) land without touching this one.
 * Component status and metrics (#106) sit above the logs.
 */
export function SystemsTab() {
  const status = useSystemStatus();
  return (
    <>
      <ComponentStatusCards status={status} />
      <MetricsPanel metrics={status.metrics} unavailable={status.metricsUnavailable} />
      <div className="admin-two">
        <RefreshLogPanel />
        <DeliveryLogPanel />
      </div>
    </>
  );
}
