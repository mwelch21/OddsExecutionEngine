import { PushToggle } from "../../PushToggle";
import { AdminPanel } from "../AdminPanel";

/** The temporary Enable-notifications button, here until onboarding (#64) owns it. */
export function NotificationsSection({ onRegistered }: { onRegistered?: () => void }) {
  return (
    <AdminPanel title="Notifications">
      <div className="admin-row">
        <PushToggle onEnabled={onRegistered} />
      </div>
      <p className="admin-muted">
        Subscribes this browser to watch alerts. Temporary home until onboarding lands.
      </p>
    </AdminPanel>
  );
}
