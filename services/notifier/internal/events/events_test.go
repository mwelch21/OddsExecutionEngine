package events

import (
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

const contractsDir = "../../../../contracts/events"

// Every example in contracts/events/examples must validate against its schema
// and decode into the notifier's types: the Go half of the contract test.
func TestContractExamplesValidateAndDecode(t *testing.T) {
	examples, err := filepath.Glob(filepath.Join(contractsDir, "examples", "*.json"))
	if err != nil || len(examples) == 0 {
		t.Fatalf("no contract examples found: %v", err)
	}
	compiler := jsonschema.NewCompiler()
	compiler.AssertFormat()

	for _, path := range examples {
		eventType := strings.TrimSuffix(filepath.Base(path), ".json")
		t.Run(eventType, func(t *testing.T) {
			schema, err := compiler.Compile(filepath.Join(contractsDir, eventType+".json"))
			if err != nil {
				t.Fatalf("compiling schema: %v", err)
			}
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			instance, err := jsonschema.UnmarshalJSON(strings.NewReader(string(raw)))
			if err != nil {
				t.Fatal(err)
			}
			if err := schema.Validate(instance); err != nil {
				t.Fatalf("example does not match schema: %v", err)
			}

			var event CloudEvent
			if err := json.Unmarshal(raw, &event); err != nil {
				t.Fatalf("decoding envelope: %v", err)
			}
			if event.Type != eventType || event.ID == "" || event.Time.IsZero() {
				t.Fatalf("envelope decoded badly: %+v", event)
			}
		})
	}
}

func TestRenderDestinationTest(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join(contractsDir, "examples", TypeDestinationTestV1+".json"))
	if err != nil {
		t.Fatal(err)
	}
	var event CloudEvent
	if err := json.Unmarshal(raw, &event); err != nil {
		t.Fatal(err)
	}

	n, err := Render(event, "iPhone", testOrigin)
	if err != nil {
		t.Fatal(err)
	}
	if n.Title != "OddsCafe test" || n.Body != "Notifications are working on iPhone." || n.URL != testOrigin+"/" {
		t.Fatalf("unexpected notification: %+v", n)
	}
}

func TestDestinationTestExpiresTenMinutesAfterItWasRequested(t *testing.T) {
	event := CloudEvent{Type: TypeDestinationTestV1, Time: time.Date(2026, 10, 18, 18, 0, 0, 0, time.UTC)}
	if got := ExpiresAt(event); !got.Equal(event.Time.Add(10 * time.Minute)) {
		t.Fatalf("expires at %s", got)
	}
}

func TestOpportunityExpiresWhenItStopsBeingValid(t *testing.T) {
	event := loadExample(t, TypeOpportunityIdentifiedV1)
	want := time.Date(2026, 10, 19, 6, 0, 0, 0, time.UTC)
	if got := ExpiresAt(event); !got.Equal(want) {
		t.Fatalf("expires at %s, want %s", got, want)
	}
}

// Events written before expires_at existed must not burst out on deploy.
func TestOpportunityWithoutExpiryIsAlreadyExpired(t *testing.T) {
	event := loadExample(t, TypeOpportunityIdentifiedV1)
	var data map[string]any
	json.Unmarshal(event.Data, &data) //nolint:errcheck // example is valid
	delete(data, "expires_at")
	event.Data, _ = json.Marshal(data)

	if got := ExpiresAt(event); !got.Equal(event.Time) {
		t.Fatalf("expires at %s, want the event time %s", got, event.Time)
	}
}

func TestOpportunityIsDeliveredToEveryDestination(t *testing.T) {
	if Targeted(TypeOpportunityIdentifiedV1) {
		t.Fatal("opportunity events fan out to every active destination")
	}
	if !slices.Contains(Delivered, TypeOpportunityIdentifiedV1) {
		t.Fatal("opportunity events are not picked up by fan-out")
	}
}

func TestRenderOpportunity(t *testing.T) {
	n, err := Render(loadExample(t, TypeOpportunityIdentifiedV1), "iPhone", testOrigin)
	if err != nil {
		t.Fatal(err)
	}
	want := Notification{
		Title: "Knicks @ Celtics",
		Body:  "Knicks +125 @ DraftKings · target +100 · fillable",
		URL:   testOrigin + "/?event=nba-knicks-celtics-2026-04-11&opportunity=opp-1",
		Tag:   "opportunity-opp-1",
	}
	if n != want {
		t.Fatalf("got  %+v\nwant %+v", n, want)
	}
}

func TestRenderOpportunityBodyPerMarket(t *testing.T) {
	cases := []struct {
		name, market, selection string
		line                    any
		best, target            int
		want                    string
	}{
		{"total", "total", "over", 221.5, -105, -110, "Over 221.5 -105 @ FanDuel · target -110 · fillable"},
		{"spread favourite", "spread", "knicks", -3.5, -105, -110, "Knicks -3.5 -105 @ FanDuel · target -110 · fillable"},
		{"spread underdog", "spread", "celtics", 3.0, 100, -105, "Celtics +3 +100 @ FanDuel · target -105 · fillable"},
		{"stored team name", "moneyline", "los angeles rams", nil, 150, 140, "Los Angeles Rams +150 @ FanDuel · target +140 · fillable"},
		{"accented name", "spread", "montréal canadiens", -1.5, 180, 170, "Montréal Canadiens -1.5 +180 @ FanDuel · target +170 · fillable"},
		{"accented first letter", "moneyline", "élan", nil, 120, 110, "Élan +120 @ FanDuel · target +110 · fillable"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			event := loadExample(t, TypeOpportunityIdentifiedV1)
			var data map[string]any
			json.Unmarshal(event.Data, &data) //nolint:errcheck // example is valid
			data["market_type"], data["selection"], data["line"] = c.market, c.selection, c.line
			data["target_price"] = c.target
			data["best"] = map[string]any{"sportsbook": "FanDuel", "price": c.best, "quoted_at": nil}
			event.Data, _ = json.Marshal(data)

			n, err := Render(event, "iPhone", testOrigin)
			if err != nil {
				t.Fatal(err)
			}
			if n.Body != c.want {
				t.Fatalf("body = %q, want %q", n.Body, c.want)
			}
		})
	}
}

// An event with no participants still renders; the title falls back.
func TestRenderOpportunityWithoutTeams(t *testing.T) {
	event := loadExample(t, TypeOpportunityIdentifiedV1)
	var data map[string]any
	json.Unmarshal(event.Data, &data) //nolint:errcheck // example is valid
	data["event"].(map[string]any)["home"] = nil
	event.Data, _ = json.Marshal(data)

	n, err := Render(event, "iPhone", testOrigin)
	if err != nil {
		t.Fatal(err)
	}
	if n.Title != "Opportunity" {
		t.Fatalf("title = %q", n.Title)
	}
}

const testOrigin = "https://phone.tailnet.ts.net"

func loadExample(t *testing.T, eventType string) CloudEvent {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(contractsDir, "examples", eventType+".json"))
	if err != nil {
		t.Fatal(err)
	}
	var event CloudEvent
	if err := json.Unmarshal(raw, &event); err != nil {
		t.Fatal(err)
	}
	return event
}
