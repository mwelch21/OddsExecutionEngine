import { PushToggle } from "../../PushToggle";
import { AdminPanel } from "../AdminPanel";

/** The temporary Enable-notifications button, here until onboarding (#64) owns it. */
export function NotificationsSection() {
  return (
    <AdminPanel title="Notifications">
      <div className="admin-row">
        <PushToggle />
      </div>
      <p className="admin-muted">
        Subscribes this browser to watch alerts. Temporary home until onboarding lands.
      </p>
    </AdminPanel>
  );
}
