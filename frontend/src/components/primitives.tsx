import { useCallback, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
};

export function Button({ className = "", variant = "secondary", ...props }: ButtonProps) {
  return <button className={`button button-${variant} ${className}`} {...props} />;
}

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{children}</section>;
}

export function Pill({
  children,
  tone = "neutral"
}: {
  children: ReactNode;
  tone?: "neutral" | "good" | "warn" | "accent";
}) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

const COLLAPSED_KEY_PREFIX = "oddscafe.collapsed.";

function readCollapsed(id: string): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY_PREFIX + id) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(id: string, collapsed: boolean) {
  try {
    if (collapsed) window.localStorage.setItem(COLLAPSED_KEY_PREFIX + id, "1");
    else window.localStorage.removeItem(COLLAPSED_KEY_PREFIX + id);
  } catch {
    // Storage blocked: the section still toggles for this visit.
  }
}

/**
 * Open/closed state for one collapsible section, remembered per browser.
 * A convenience only: blocked storage means every section starts open.
 * `expand` opens the section without toggling, for content that must show.
 */
export function useCollapsed(id: string): [boolean, () => void, () => void] {
  const [collapsed, setCollapsed] = useState(() => readCollapsed(id));
  const toggle = useCallback(() => {
    setCollapsed((current) => {
      writeCollapsed(id, !current);
      return !current;
    });
  }, [id]);
  const expand = useCallback(() => {
    setCollapsed(false);
    writeCollapsed(id, false);
  }, [id]);
  return [collapsed, toggle, expand];
}

/** Chevron that opens or closes the section named by `label`. */
export function CollapseToggle({
  collapsed,
  onToggle,
  label
}: {
  collapsed: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <Button
      variant="ghost"
      className={`collapse-toggle${collapsed ? " collapsed" : ""}`}
      aria-expanded={!collapsed}
      aria-label={`${collapsed ? "Expand" : "Collapse"} ${label}`}
      title={collapsed ? "Expand" : "Collapse"}
      onClick={onToggle}
    >
      <ChevronDown size={16} />
    </Button>
  );
}
