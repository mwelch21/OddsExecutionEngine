import { useState } from "react";
import { AutoRefreshSection } from "./controls/AutoRefreshSection";
import { DestinationsSection } from "./controls/DestinationsSection";
import { NotificationsSection } from "./controls/NotificationsSection";

/**
 * The operator's switches (#95 Variant A). One section card per control group,
 * each its own file.
 */
export function ControlsTab() {
  // Bumped when this browser subscribes, so the device list shows it at once.
  const [devicesVersion, setDevicesVersion] = useState(0);
  return (
    <div className="admin-cards">
      <NotificationsSection onRegistered={() => setDevicesVersion((version) => version + 1)} />
      <DestinationsSection reloadKey={devicesVersion} />
      <AutoRefreshSection />
    </div>
  );
}
