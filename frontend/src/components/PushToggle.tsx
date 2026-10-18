import { useEffect, useState } from "react";
import { BellOff, BellRing, Send } from "lucide-react";
import {
  currentSubscriptionEndpoint,
  enablePush,
  listDestinations,
  pushSupport,
  sendTestNotification
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
  const [destinationId, setDestinationId] = useState<string | null>(null);
  const [testState, setTestState] = useState<"idle" | "sending" | "sent" | "error">("idle");

  useEffect(() => {
    if (support !== "supported") return;
    let cancelled = false;
    Promise.all([currentSubscriptionEndpoint(), listDestinations()])
      .then(([endpoint, destinations]) => {
        if (cancelled) return;
        const mine = destinations.find((destination) => destination.address === endpoint);
        if (!endpoint || !mine) {
          setState("off");
          return;
        }
        setDestinationId(mine.id);
        setState(mine.active ? "on" : "disabled");
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
  async function handleTest() {
    if (!destinationId) return;
    setTestState("sending");
    setDetail("");
    try {
      await sendTestNotification(destinationId);
      setTestState("sent");
    } catch (error: unknown) {
      setTestState("error");
      setDetail(error instanceof Error ? error.message : "Test failed");
    }
  }

  if (state === "on") {
    return (
      <>
        <Pill tone="good">
          <BellRing size={14} />
          Notifications on
        </Pill>
        <Button
          variant="ghost"
          onClick={handleTest}
          disabled={!destinationId || testState === "sending"}
          title={detail || "Sends one push to this device through the notifier"}
        >
          <Send size={14} />
          {testState === "sending"
            ? "Sending…"
            : testState === "sent"
              ? "Test sent"
              : testState === "error"
                ? "Retry test"
                : "Send test"}
        </Button>
      </>
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
      setDestinationId(destination.id);
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
