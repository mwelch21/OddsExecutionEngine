import { AutoRefreshSection } from "./controls/AutoRefreshSection";
import { NotificationsSection } from "./controls/NotificationsSection";

/**
 * The operator's switches (#95 Variant A). One section per control group, each
 * its own file, so the device list (#70) adds a section beside these.
 */
export function ControlsTab() {
  return (
    <div className="admin-stack">
      <AutoRefreshSection />
      <NotificationsSection />
    </div>
  );
}
