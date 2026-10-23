package events

import (
	"encoding/json"
	"os"
	"path/filepath"
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

	n, err := Render(event, "iPhone")
	if err != nil {
		t.Fatal(err)
	}
	if n.Title != "OddsCafe test" || n.Body != "Notifications are working on iPhone." || n.URL != "/" {
		t.Fatalf("unexpected notification: %+v", n)
	}
}

func TestDestinationTestMaxAgeIsTenMinutes(t *testing.T) {
	if got := MaxAge(TypeDestinationTestV1); got != 10*time.Minute {
		t.Fatalf("max age = %s", got)
	}
}
