import { AutoRefreshSection } from "./controls/AutoRefreshSection";
import { NotificationsSection } from "./controls/NotificationsSection";

/**
 * The operator's switches (#95 Variant A). One section card per control group,
 * each its own file, so the device list (#70) adds one more card to the grid.
 */
export function ControlsTab() {
  return (
    <div className="admin-cards">
      <NotificationsSection />
      <AutoRefreshSection />
    </div>
  );
}
