package push

import (
	"encoding/json"
	"fmt"
	"net/url"
	"strings"

	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/events"
)

// MaxPayloadBytes keeps the plaintext inside one 4096-byte Web Push record
// once aes128gcm adds its header, padding delimiter and tag (RFC 8291).
const MaxPayloadBytes = 3993

// declarativeMagic marks a Declarative Web Push message (WebKit, iOS 18.4+).
const declarativeMagic = 8030

type declarative struct {
	WebPush      int                     `json:"web_push"`
	Notification declarativeNotification `json:"notification"`
}

type declarativeNotification struct {
	Title    string `json:"title"`
	Body     string `json:"body"`
	Navigate string `json:"navigate"`
	Tag      string `json:"tag,omitempty"`
}

// Payload is the plaintext sent to one endpoint. Apple endpoints get
// Declarative Web Push: iOS 18.4+ shows it and opens `navigate` itself, with no
// service worker in the path, which avoids WebKit's cold-launch click bugs
// (#66). Without `mutable`, the service worker never sees it on 18.4+; older
// iOS hands it to the service worker, which reads the nested shape. Every
// other browser gets the plain notification the service worker displays.
func Payload(endpoint string, n events.Notification) ([]byte, error) {
	var body any = n
	if isApple(endpoint) {
		body = declarative{
			WebPush: declarativeMagic,
			Notification: declarativeNotification{
				Title: n.Title, Body: n.Body, Navigate: n.URL, Tag: n.Tag,
			},
		}
	}
	raw, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("encoding notification: %w", err)
	}
	if len(raw) > MaxPayloadBytes {
		return nil, fmt.Errorf("notification is %d bytes, over the %d-byte Web Push limit", len(raw), MaxPayloadBytes)
	}
	return raw, nil
}

func isApple(endpoint string) bool {
	u, err := url.Parse(endpoint)
	if err != nil {
		return false
	}
	host := u.Hostname()
	return host == "web.push.apple.com" || strings.HasSuffix(host, ".push.apple.com")
}
