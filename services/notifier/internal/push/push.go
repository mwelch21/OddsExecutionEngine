// Package push sends one rendered notification to one Web Push subscription.
package push

import (
	"context"
	"crypto/ecdh"
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	webpush "github.com/SherClockHolmes/webpush-go"

	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/events"
)

// Subscription is a browser's push endpoint and encryption keys.
type Subscription struct {
	Endpoint string
	P256dh   string
	Auth     string
}

// Result is what the push service answered.
type Result struct {
	StatusCode int
	Body       string
}

// Sender delivers a notification. The interface lets tests swap the network.
type Sender interface {
	Send(ctx context.Context, sub Subscription, n events.Notification, ttl time.Duration) (Result, error)
}

// WebPushSender signs with VAPID and sends via webpush-go.
type WebPushSender struct {
	publicKey  string
	privateKey string
	subject    string
	client     *http.Client
}

// NewWebPushSender builds a sender. webpush-go adds "mailto:" itself unless
// the subject is an https URL, so a configured "mailto:" prefix is stripped
// here; otherwise the JWT would carry "mailto:mailto:…" and Apple rejects it.
func NewWebPushSender(publicKey, privateKey, subject string) *WebPushSender {
	return &WebPushSender{
		publicKey:  publicKey,
		privateKey: privateKey,
		subject:    strings.TrimPrefix(subject, "mailto:"),
		client:     &http.Client{Timeout: 15 * time.Second},
	}
}

// Send encrypts and posts the notification. A non-2xx answer is a Result, not
// an error: the caller decides what each status means.
func (s *WebPushSender) Send(ctx context.Context, sub Subscription, n events.Notification, ttl time.Duration) (Result, error) {
	if err := checkKeys(sub); err != nil {
		return Result{}, err
	}
	payload, err := Payload(sub.Endpoint, n)
	if err != nil {
		return Result{}, err
	}
	resp, err := webpush.SendNotificationWithContext(ctx, payload, &webpush.Subscription{
		Endpoint: sub.Endpoint,
		Keys:     webpush.Keys{P256dh: sub.P256dh, Auth: sub.Auth},
	}, &webpush.Options{
		HTTPClient:      s.client,
		Subscriber:      s.subject,
		VAPIDPublicKey:  s.publicKey,
		VAPIDPrivateKey: s.privateKey,
		TTL:             max(int(ttl.Seconds()), 0),
		Urgency:         webpush.UrgencyHigh,
	})
	if err != nil {
		return Result{}, fmt.Errorf("sending push: %w", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
	return Result{StatusCode: resp.StatusCode, Body: string(body)}, nil
}

// checkKeys rejects a subscription whose keys can never encrypt: p256dh must
// be a P-256 public key and auth a 16-byte secret (RFC 8291). webpush-go
// reports the same problem as an ordinary error, which would read as a
// network failure and be retried for the event's whole max age.
func checkKeys(sub Subscription) error {
	p256dh, err := decodeKey(sub.P256dh)
	if err == nil {
		_, err = ecdh.P256().NewPublicKey(p256dh)
	}
	if err != nil {
		return fmt.Errorf("%w: subscription p256dh is not a P-256 public key", ErrUnsendable)
	}
	if auth, err := decodeKey(sub.Auth); err != nil || len(auth) != 16 {
		return fmt.Errorf("%w: subscription auth is not a 16-byte secret", ErrUnsendable)
	}
	return nil
}

// decodeKey accepts the base64 spellings browsers and webpush-go accept.
func decodeKey(key string) ([]byte, error) {
	var err error
	for _, enc := range []*base64.Encoding{
		base64.RawURLEncoding, base64.URLEncoding, base64.RawStdEncoding, base64.StdEncoding,
	} {
		var raw []byte
		if raw, err = enc.DecodeString(key); err == nil {
			return raw, nil
		}
	}
	return nil, err
}
