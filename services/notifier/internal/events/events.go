// Package events knows the public event types the notifier delivers: how each
// fans out, how long it stays worth sending, and how it renders as a push.
//
// The event is pure data (ADR-014); rendering belongs to the channel.
package events

import (
	"encoding/json"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// Public event types this notifier delivers. Others are left undispatched in
// the outbox until a release that understands them.
const (
	TypeDestinationTestV1       = "oddsengine.destination.test.v1"
	TypeOpportunityIdentifiedV1 = "oddsengine.opportunity.identified.v1"
)

// Delivered lists the types fan-out picks up today.
var Delivered = []string{TypeDestinationTestV1, TypeOpportunityIdentifiedV1}

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

// OpportunityIdentifiedData is the part of opportunity.identified.v1 data the
// notifier renders. The full shape is the JSON Schema under contracts/events.
type OpportunityIdentifiedData struct {
	OpportunityID string `json:"opportunity_id"`
	Event         struct {
		ID   string  `json:"id"`
		Home *string `json:"home"`
		Away *string `json:"away"`
	} `json:"event"`
	MarketType  string   `json:"market_type"`
	Selection   string   `json:"selection"`
	Line        *float64 `json:"line"`
	TargetPrice int      `json:"target_price"`
	Best        struct {
		Sportsbook string `json:"sportsbook"`
		Price      int    `json:"price"`
	} `json:"best"`
	ExpiresAt *time.Time `json:"expires_at"`
}

// Targeted reports whether an event goes to the single destination named in
// its subject rather than to every active destination.
func Targeted(eventType string) bool {
	return eventType == TypeDestinationTestV1
}

// ExpiresAt is when an event stops being worth delivering (ADR-015). Past it,
// a delivery is expired instead of sent.
func ExpiresAt(event CloudEvent) time.Time {
	switch event.Type {
	case TypeDestinationTestV1:
		return event.Time.Add(10 * time.Minute)
	case TypeOpportunityIdentifiedV1:
		// The opportunity's own validity. An event written before expires_at
		// existed, or one that cannot be read, counts as already expired, so a
		// deploy never sends a burst of stale opportunities.
		var data OpportunityIdentifiedData
		if err := json.Unmarshal(event.Data, &data); err != nil || data.ExpiresAt == nil {
			return event.Time
		}
		return *data.ExpiresAt
	default:
		return event.Time.Add(24 * time.Hour)
	}
}

// Notification is the push payload the service worker displays.
type Notification struct {
	Title string `json:"title"`
	Body  string `json:"body"`
	URL   string `json:"url"`
	Tag   string `json:"tag,omitempty"`
}

// Render turns an event into the notification shown on a destination. The URL
// is absolute under appOrigin: Declarative Web Push navigates to it directly.
func Render(event CloudEvent, destinationLabel, appOrigin string) (Notification, error) {
	switch event.Type {
	case TypeDestinationTestV1:
		var data DestinationTestData
		if err := json.Unmarshal(event.Data, &data); err != nil {
			return Notification{}, fmt.Errorf("decoding %s data: %w", event.Type, err)
		}
		return Notification{
			Title: "OddsCafe test",
			Body:  fmt.Sprintf("Notifications are working on %s.", destinationLabel),
			URL:   appOrigin + "/",
			Tag:   "destination-test",
		}, nil
	case TypeOpportunityIdentifiedV1:
		var data OpportunityIdentifiedData
		if err := json.Unmarshal(event.Data, &data); err != nil {
			return Notification{}, fmt.Errorf("decoding %s data: %w", event.Type, err)
		}
		return renderOpportunity(data, appOrigin), nil
	default:
		return Notification{}, fmt.Errorf("no renderer for %s", event.Type)
	}
}

// renderOpportunity: title is the matchup; body is
// "<selection> <best price> @ <book> · target <target price> · fillable".
// The link is the root with query parameters, never /events/{id}, which is an
// API path (#66).
func renderOpportunity(data OpportunityIdentifiedData, appOrigin string) Notification {
	title := "Opportunity"
	if data.Event.Away != nil && data.Event.Home != nil {
		title = *data.Event.Away + " @ " + *data.Event.Home
	}

	selection := displayName(data.Selection)
	if data.Line != nil {
		line := strconv.FormatFloat(*data.Line, 'f', -1, 64)
		if data.MarketType == "spread" && *data.Line > 0 {
			line = "+" + line
		}
		selection += " " + line
	}

	query := url.Values{}
	query.Set("event", data.Event.ID)
	query.Set("opportunity", data.OpportunityID)

	return Notification{
		Title: title,
		Body: fmt.Sprintf("%s %s @ %s · target %s · fillable",
			selection, americanOdds(data.Best.Price), data.Best.Sportsbook,
			americanOdds(data.TargetPrice)),
		URL: appOrigin + "/?" + query.Encode(),
		// One opportunity is one notification: a repeat replaces, never stacks.
		Tag: "opportunity-" + data.OpportunityID,
	}
}

func americanOdds(price int) string {
	if price > 0 {
		return "+" + strconv.Itoa(price)
	}
	return strconv.Itoa(price)
}

// displayName turns a stored selection such as "montréal canadiens" into
// "Montréal Canadiens". Rune-safe: a name may start with an accented letter.
func displayName(key string) string {
	words := strings.Fields(strings.ReplaceAll(key, "_", " "))
	for i, w := range words {
		r, size := utf8.DecodeRuneInString(w)
		words[i] = string(unicode.ToUpper(r)) + w[size:]
	}
	return strings.Join(words, " ")
}
