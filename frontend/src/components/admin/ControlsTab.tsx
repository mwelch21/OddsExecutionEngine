import { AutoRefreshSection } from "./controls/AutoRefreshSection";
import { DestinationsSection } from "./controls/DestinationsSection";
import { NotificationsSection } from "./controls/NotificationsSection";

/**
 * The operator's switches (#95 Variant A). One section card per control group,
 * each its own file.
 */
export function ControlsTab() {
  return (
    <div className="admin-cards">
      <NotificationsSection />
      <DestinationsSection />
      <AutoRefreshSection />
    </div>
  );
}
