package push

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/events"
)

var opportunity = events.Notification{
	Title: "Knicks @ Celtics",
	Body:  "Knicks +125 @ DraftKings · target +100 · fillable",
	URL:   "https://phone.tailnet.ts.net/?event=e-1&opportunity=opp-1",
	Tag:   "opportunity-opp-1",
}

// iOS 18.4+ shows and navigates a declarative message itself, with no service
// worker code in the path: that is what makes a cold-launch tap reliable.
func TestAppleEndpointsGetDeclarativeWebPush(t *testing.T) {
	raw, err := Payload("https://web.push.apple.com/QFakeToken", opportunity)
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if err := json.Unmarshal(raw, &got); err != nil {
		t.Fatal(err)
	}
	if got["web_push"] != float64(8030) {
		t.Fatalf("web_push = %v, want 8030", got["web_push"])
	}
	if _, mutable := got["mutable"]; mutable {
		t.Fatal("mutable would route the push through the service worker again")
	}
	n, _ := got["notification"].(map[string]any)
	if n["title"] != opportunity.Title || n["body"] != opportunity.Body ||
		n["navigate"] != opportunity.URL || n["tag"] != opportunity.Tag {
		t.Fatalf("notification = %v", n)
	}
}

func TestOtherEndpointsGetThePlainPayloadTheServiceWorkerShows(t *testing.T) {
	for _, endpoint := range []string{
		"https://fcm.googleapis.com/fcm/send/abc",
		"https://updates.push.services.mozilla.com/wpush/v2/abc",
		"https://web.push.apple.com.evil.example/abc",
	} {
		raw, err := Payload(endpoint, opportunity)
		if err != nil {
			t.Fatal(err)
		}
		var got events.Notification
		if err := json.Unmarshal(raw, &got); err != nil {
			t.Fatal(err)
		}
		if got != opportunity || strings.Contains(string(raw), "web_push") {
			t.Fatalf("%s: payload = %s", endpoint, raw)
		}
	}
}

func TestPayloadStaysUnderTheWebPushLimit(t *testing.T) {
	long := opportunity
	long.Body = strings.Repeat("x", 4000)

	if _, err := Payload("https://web.push.apple.com/QFakeToken", long); err == nil {
		t.Fatal("an oversized payload must be rejected, not sent and dropped")
	}
	raw, err := Payload("https://web.push.apple.com/QFakeToken", opportunity)
	if err != nil || len(raw) > MaxPayloadBytes {
		t.Fatalf("typical payload: %d bytes, err %v", len(raw), err)
	}
}
