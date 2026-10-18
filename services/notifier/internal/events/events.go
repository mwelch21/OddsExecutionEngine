// Package events knows the public event types the notifier delivers: how each
// fans out, how long it stays worth sending, and how it renders as a push.
//
// The event is pure data (ADR-014); rendering belongs to the channel.
package events

import (
	"encoding/json"
	"fmt"
	"time"
)

// Public event types this notifier delivers. Others are left undispatched in
// the outbox until a release that understands them.
const (
	TypeDestinationTestV1       = "oddsengine.destination.test.v1"
	TypeOpportunityIdentifiedV1 = "oddsengine.opportunity.identified.v1"
)

// Delivered lists the types fan-out picks up today.
var Delivered = []string{TypeDestinationTestV1}

// CloudEvent is the structured-mode envelope stored in public_events.payload.
type CloudEvent struct {
	ID          string          `json:"id"`
	Source      string          `json:"source"`
	SpecVersion string          `json:"specversion"`
	Type        string          `json:"type"`
	Time        time.Time       `json:"time"`
	Subject     string          `json:"subject,omitempty"`
	DataSchema  string          `json:"dataschema"`
	Data        json.RawMessage `json:"data"`
}

// DestinationTestData is the data of destination.test.v1.
type DestinationTestData struct {
	DestinationID string    `json:"destination_id"`
	RequestedAt   time.Time `json:"requested_at"`
}

// Targeted reports whether an event goes to the single destination named in
// its subject rather than to every active destination.
func Targeted(eventType string) bool {
	return eventType == TypeDestinationTestV1
}

// MaxAge is how long an event stays worth delivering (ADR-015). Past it, a
// delivery is expired instead of sent.
func MaxAge(eventType string) time.Duration {
	switch eventType {
	case TypeDestinationTestV1:
		return 10 * time.Minute
	default:
		return 24 * time.Hour
	}
}

// Notification is the push payload the service worker displays.
type Notification struct {
	Title string `json:"title"`
	Body  string `json:"body"`
	URL   string `json:"url"`
	Tag   string `json:"tag,omitempty"`
}

// Render turns an event into the notification shown on a destination.
func Render(event CloudEvent, destinationLabel string) (Notification, error) {
	switch event.Type {
	case TypeDestinationTestV1:
		var data DestinationTestData
		if err := json.Unmarshal(event.Data, &data); err != nil {
			return Notification{}, fmt.Errorf("decoding %s data: %w", event.Type, err)
		}
		return Notification{
			Title: "OddsCafe test",
			Body:  fmt.Sprintf("Notifications are working on %s.", destinationLabel),
			URL:   "/",
			Tag:   "destination-test",
		}, nil
	default:
		return Notification{}, fmt.Errorf("no renderer for %s", event.Type)
	}
}
