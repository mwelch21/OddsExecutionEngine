import { useEffect } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

/**
 * PROTOTYPE ONLY. Floating variant switcher for throwaway UI prototypes.
 * Cycles `?variant=` in the URL; arrow keys work unless an input has focus.
 */
export function PrototypeSwitcher({
  variants,
  current,
  onChange
}: {
  variants: { key: string; name: string }[];
  current: string;
  onChange: (key: string) => void;
}) {
  const index = Math.max(
    0,
    variants.findIndex((variant) => variant.key === current)
  );

  function step(delta: number) {
    const next = variants[(index + delta + variants.length) % variants.length];
    const params = new URLSearchParams(window.location.search);
    params.set("variant", next.key);
    window.history.replaceState(null, "", `?${params.toString()}`);
    onChange(next.key);
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable]")) return;
      if (event.key === "ArrowLeft") step(-1);
      if (event.key === "ArrowRight") step(1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!import.meta.env.DEV) return null;

  return (
    <div className="proto-switcher" role="toolbar" aria-label="Prototype variant">
      <button onClick={() => step(-1)} aria-label="Previous variant">
        <ChevronLeft size={16} />
      </button>
      <span>
        {variants[index].key} · {variants[index].name}
      </span>
      <button onClick={() => step(1)} aria-label="Next variant">
        <ChevronRight size={16} />
      </button>
    </div>
  );
}
