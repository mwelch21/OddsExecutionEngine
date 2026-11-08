import type { ComponentType, MouseEvent, ReactNode } from "react";
import { Gauge, Settings2, ShieldCheck } from "lucide-react";
import { routeUrl, type AdminTab } from "../../lib/deepLink";
import { ControlsTab } from "./ControlsTab";
import { CreditsTab } from "./CreditsTab";
import { SystemsTab } from "./SystemsTab";

const TABS: { key: AdminTab; label: string; icon: ReactNode; Tab: ComponentType }[] = [
  { key: "systems", label: "Systems", icon: <ShieldCheck size={16} />, Tab: SystemsTab },
  { key: "credits", label: "Credits", icon: <Gauge size={16} />, Tab: CreditsTab },
  { key: "controls", label: "Controls", icon: <Settings2 size={16} />, Tab: ControlsTab }
];

/**
 * The operator's page (#90): a tab strip over one tab at a time. Each tab is its
 * own URL (`/admin/<tab>`, ADR-018), so a reload or a notification link lands on it.
 */
export function AdminView({
  tab,
  onSelectTab
}: {
  tab: AdminTab;
  onSelectTab: (tab: AdminTab) => void;
}) {
  function handleClick(event: MouseEvent<HTMLAnchorElement>, key: AdminTab) {
    // Let a modified click open the tab in a new browser tab, as a link would.
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    if (key !== tab) onSelectTab(key);
  }

  return (
    <main className="workspace admin-view">
      <nav className="admin-tabstrip" aria-label="Admin view">
        {TABS.map(({ key, label, icon }) => (
          <a
            key={key}
            href={routeUrl({ view: "admin", tab: key })}
            className={key === tab ? "active" : undefined}
            aria-current={key === tab ? "page" : undefined}
            onClick={(event) => handleClick(event, key)}
          >
            {icon}
            {label}
          </a>
        ))}
      </nav>
      {TABS.filter(({ key }) => key === tab).map(({ key, Tab }) => (
        <Tab key={key} />
      ))}
    </main>
  );
}
