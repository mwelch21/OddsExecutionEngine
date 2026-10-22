// Package push sends one rendered notification to one Web Push subscription.
package push

import (
	"context"
	"encoding/json"
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
	payload, err := json.Marshal(n)
	if err != nil {
		return Result{}, fmt.Errorf("encoding notification: %w", err)
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
