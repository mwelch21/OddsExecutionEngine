import { useEffect, useState } from "react";
import { BellOff, BellRing } from "lucide-react";
import {
  currentSubscriptionEndpoint,
  enablePush,
  listDestinations,
  pushSupport
} from "../lib/push";
import { Button, Pill } from "./primitives";

type PushState = "checking" | "off" | "enabling" | "on" | "disabled" | "error";

/**
 * Plain "Enable notifications" control: subscribes this browser as a destination.
 * Phone onboarding polish is its own feature (#64); this only has to work.
 */
export function PushToggle() {
  const support = pushSupport();
  const [state, setState] = useState<PushState>("checking");
  const [detail, setDetail] = useState("");

  useEffect(() => {
    if (support !== "supported") return;
    let cancelled = false;
    Promise.all([currentSubscriptionEndpoint(), listDestinations()])
      .then(([endpoint, destinations]) => {
        if (cancelled) return;
        const mine = destinations.find((destination) => destination.address === endpoint);
        if (!endpoint || !mine) setState("off");
        else setState(mine.active ? "on" : "disabled");
      })
      .catch(() => {
        if (!cancelled) setState("off");
      });
    return () => {
      cancelled = true;
    };
  }, [support]);

  if (support === "needs-install") {
    return (
      <Pill tone="warn">
        <BellOff size={14} />
        Add to Home Screen to get notifications
      </Pill>
    );
  }
  if (support === "unsupported") {
    return (
      <Pill>
        <BellOff size={14} />
        Notifications unavailable
      </Pill>
    );
  }
  if (state === "on") {
    return (
      <Pill tone="good">
        <BellRing size={14} />
        Notifications on
      </Pill>
    );
  }
  if (state === "disabled") {
    return (
      <Pill tone="warn">
        <BellOff size={14} />
        This device was removed
      </Pill>
    );
  }

  async function handleEnable() {
    setState("enabling");
    setDetail("");
    try {
      const destination = await enablePush();
      setState(destination.active ? "on" : "disabled");
    } catch (error: unknown) {
      setState("error");
      setDetail(error instanceof Error ? error.message : "Could not enable notifications");
    }
  }

  return (
    <Button
      variant="secondary"
      onClick={handleEnable}
      disabled={state === "checking" || state === "enabling"}
      title={detail || undefined}
    >
      <BellRing size={14} />
      {state === "enabling"
        ? "Enabling…"
        : state === "error"
          ? "Retry notifications"
          : "Enable notifications"}
    </Button>
  );
}
