package notifier

import (
	"context"
	"crypto/ecdh"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	webpush "github.com/SherClockHolmes/webpush-go"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/events"
	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/push"
	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/store"
)

// These tests need a Postgres database migrated by Alembic (the schema's only
// owner). `just test-notifier` prepares one and sets NOTIFIER_TEST_DATABASE_URL.

type fakePushService struct {
	server *httptest.Server
	mu     sync.Mutex
	hits   []*http.Request
	status int
}

func newFakePushService(t *testing.T) *fakePushService {
	f := &fakePushService{status: http.StatusCreated}
	f.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body) //nolint:errcheck // test server
		f.mu.Lock()
		f.hits = append(f.hits, r)
		status := f.status
		f.mu.Unlock()
		w.WriteHeader(status)
	}))
	t.Cleanup(f.server.Close)
	return f
}

func (f *fakePushService) requests() []*http.Request {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]*http.Request(nil), f.hits...)
}

type harness struct {
	t        *testing.T
	ctx      context.Context
	url      string
	pool     *pgxpool.Pool
	push     *fakePushService
	notifier *Notifier
}

func newHarness(t *testing.T) *harness {
	t.Helper()
	url := os.Getenv("NOTIFIER_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("NOTIFIER_TEST_DATABASE_URL not set; run `just test-notifier`")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	if _, err := pool.Exec(ctx,
		`TRUNCATE deliveries, public_events, destinations CASCADE`); err != nil {
		t.Fatalf("resetting tables (is the test DB migrated?): %v", err)
	}

	privateKey, publicKey, err := webpush.GenerateVAPIDKeys()
	if err != nil {
		t.Fatal(err)
	}
	fake := newFakePushService(t)
	return &harness{
		t: t, ctx: ctx, url: url, pool: pool, push: fake,
		notifier: &Notifier{
			Store:     store.New(pool),
			Sender:    push.NewWebPushSender(publicKey, privateKey, "mailto:ops@example.com"),
			Log:       slog.New(slog.NewTextHandler(io.Discard, nil)),
			BatchSize: 20,
			Lease:     time.Minute,
			Now:       time.Now,
			AppOrigin: "https://phone.tailnet.ts.net",
		},
	}
}

// addDestination stores an active Web Push destination whose endpoint is the
// fake push service, with real encryption keys so webpush-go can encrypt.
func (h *harness) addDestination(label string) string {
	h.t.Helper()
	key, err := ecdh.P256().GenerateKey(rand.Reader)
	if err != nil {
		h.t.Fatal(err)
	}
	auth := make([]byte, 16)
	rand.Read(auth) //nolint:errcheck // never fails
	config, _ := json.Marshal(map[string]string{
		"p256dh": base64.RawURLEncoding.EncodeToString(key.PublicKey().Bytes()),
		"auth":   base64.RawURLEncoding.EncodeToString(auth),
	})
	id := uuid.NewString()
	if _, err := h.pool.Exec(h.ctx, `
		INSERT INTO destinations (id, channel, label, address, config)
		VALUES ($1, 'web_push', $2, $3, $4::json)`,
		id, label, h.push.server.URL+"/push/"+id, string(config)); err != nil {
		h.t.Fatal(err)
	}
	return id
}

// addTestEvent writes destination.test.v1 to the outbox the way the API does.
func (h *harness) addTestEvent(destinationID string, at time.Time) string {
	h.t.Helper()
	id := uuid.NewString()
	payload, _ := json.Marshal(map[string]any{
		"id": id, "source": "/oddsengine", "specversion": "1.0",
		"type": events.TypeDestinationTestV1, "time": at.Format(time.RFC3339Nano),
		"subject": destinationID, "dataschema": "https://example.invalid/schema.json",
		"data": map[string]string{
			"destination_id": destinationID, "requested_at": at.Format(time.RFC3339Nano),
		},
	})
	if _, err := h.pool.Exec(h.ctx,
		`INSERT INTO public_events (id, type, payload) VALUES ($1, $2, $3::json)`,
		id, events.TypeDestinationTestV1, string(payload)); err != nil {
		h.t.Fatal(err)
	}
	return id
}

// addOpportunityEvent writes opportunity.identified.v1 to the outbox the way the
// API does, from the contract example, with three matching books.
func (h *harness) addOpportunityEvent(at, expiresAt time.Time) string {
	h.t.Helper()
	raw, err := os.ReadFile("../../../../contracts/events/examples/" + events.TypeOpportunityIdentifiedV1 + ".json")
	if err != nil {
		h.t.Fatal(err)
	}
	var payload map[string]any
	if err := json.Unmarshal(raw, &payload); err != nil {
		h.t.Fatal(err)
	}
	id := uuid.NewString()
	payload["id"], payload["time"] = id, at.Format(time.RFC3339Nano)
	payload["data"].(map[string]any)["expires_at"] = expiresAt.Format(time.RFC3339Nano)
	body, _ := json.Marshal(payload)
	if _, err := h.pool.Exec(h.ctx,
		`INSERT INTO public_events (id, type, payload) VALUES ($1, $2, $3::json)`,
		id, events.TypeOpportunityIdentifiedV1, string(body)); err != nil {
		h.t.Fatal(err)
	}
	return id
}

type deliveryRow struct {
	destinationID, status string
	attempts              int
	lastError             *string
}

func (h *harness) deliveries(eventID string) []deliveryRow {
	h.t.Helper()
	rows, err := h.pool.Query(h.ctx,
		`SELECT destination_id, status, attempts, last_error FROM deliveries WHERE event_id = $1`,
		eventID)
	if err != nil {
		h.t.Fatal(err)
	}
	defer rows.Close()
	var out []deliveryRow
	for rows.Next() {
		var r deliveryRow
		if err := rows.Scan(&r.destinationID, &r.status, &r.attempts, &r.lastError); err != nil {
			h.t.Fatal(err)
		}
		out = append(out, r)
	}
	return out
}

func TestTestEventIsDeliveredToItsDestinationOnly(t *testing.T) {
	h := newHarness(t)
	target := h.addDestination("iPhone")
	h.addDestination("Mac")
	eventID := h.addTestEvent(target, time.Now())

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	got := h.deliveries(eventID)
	if len(got) != 1 || got[0].destinationID != target || got[0].status != store.StatusDelivered {
		t.Fatalf("deliveries = %+v, want one delivered to %s", got, target)
	}
	requests := h.push.requests()
	if len(requests) != 1 || requests[0].URL.Path != "/push/"+target {
		t.Fatalf("push service saw %d requests, want 1 to the target", len(requests))
	}

	var dispatched, stamped bool
	h.pool.QueryRow(h.ctx, `SELECT dispatched_at IS NOT NULL FROM public_events WHERE id = $1`,
		eventID).Scan(&dispatched) //nolint:errcheck // asserted below
	h.pool.QueryRow(h.ctx, `SELECT last_delivered_at IS NOT NULL FROM destinations WHERE id = $1`,
		target).Scan(&stamped) //nolint:errcheck // asserted below
	if !dispatched || !stamped {
		t.Fatalf("dispatched=%v last_delivered_at stamped=%v", dispatched, stamped)
	}
}

func TestOpportunityReachesEveryActiveDestinationOnce(t *testing.T) {
	h := newHarness(t)
	phone := h.addDestination("iPhone")
	mac := h.addDestination("Mac")
	removed := h.addDestination("Old iPad")
	if _, err := h.pool.Exec(h.ctx,
		`UPDATE destinations SET disabled_at = now(), disabled_reason = 'gone' WHERE id = $1`,
		removed); err != nil {
		t.Fatal(err)
	}
	eventID := h.addOpportunityEvent(time.Now(), time.Now().Add(time.Hour))

	// A second cycle must not notify again: one opportunity, one push per device,
	// however many books matched.
	for range 2 {
		if err := h.notifier.RunOnce(h.ctx); err != nil {
			t.Fatal(err)
		}
	}

	got := map[string]string{}
	for _, d := range h.deliveries(eventID) {
		got[d.destinationID] = d.status
	}
	want := map[string]string{phone: store.StatusDelivered, mac: store.StatusDelivered}
	if len(got) != len(want) || got[phone] != want[phone] || got[mac] != want[mac] {
		t.Fatalf("deliveries = %v, want delivered to the two active destinations only", got)
	}
	if n := len(h.push.requests()); n != 2 {
		t.Fatalf("push service saw %d requests, want 2", n)
	}
}

func TestOpportunityPastItsValidityExpiresUnsent(t *testing.T) {
	h := newHarness(t)
	h.addDestination("iPhone")
	eventID := h.addOpportunityEvent(time.Now().Add(-2*time.Hour), time.Now().Add(-time.Minute))

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	if got := h.deliveries(eventID); len(got) != 1 || got[0].status != store.StatusExpired {
		t.Fatalf("deliveries = %+v, want one expired", got)
	}
	if n := len(h.push.requests()); n != 0 {
		t.Fatalf("expired opportunity was sent %d times", n)
	}
}

func TestVAPIDSubjectIsSentWithASingleMailtoPrefix(t *testing.T) {
	h := newHarness(t)
	target := h.addDestination("iPhone")
	h.addTestEvent(target, time.Now())

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	requests := h.push.requests()
	if len(requests) != 1 {
		t.Fatalf("want 1 push, got %d", len(requests))
	}
	// Authorization: vapid t=<jwt>, k=<public key>
	header := requests[0].Header.Get("Authorization")
	jwt := strings.TrimSuffix(strings.SplitN(strings.TrimPrefix(header, "vapid t="), ",", 2)[0], " ")
	parts := strings.Split(jwt, ".")
	if len(parts) != 3 {
		t.Fatalf("unexpected Authorization header %q", header)
	}
	claims, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		t.Fatal(err)
	}
	var decoded struct {
		Sub string `json:"sub"`
	}
	json.Unmarshal(claims, &decoded) //nolint:errcheck // asserted below
	if decoded.Sub != "mailto:ops@example.com" {
		t.Fatalf("JWT sub = %q, want mailto:ops@example.com", decoded.Sub)
	}
}

func TestFanOutCanBeRedoneWithoutDuplicates(t *testing.T) {
	h := newHarness(t)
	target := h.addDestination("iPhone")
	eventID := h.addTestEvent(target, time.Now())
	s := h.notifier.Store

	if _, err := s.FanOut(h.ctx, events.Delivered, 20); err != nil {
		t.Fatal(err)
	}
	// Simulate a crash after inserting deliveries but before dispatched_at stuck.
	if _, err := h.pool.Exec(h.ctx,
		`UPDATE public_events SET dispatched_at = NULL WHERE id = $1`, eventID); err != nil {
		t.Fatal(err)
	}
	if _, err := s.FanOut(h.ctx, events.Delivered, 20); err != nil {
		t.Fatal(err)
	}

	if got := h.deliveries(eventID); len(got) != 1 {
		t.Fatalf("deliveries after redone fan-out = %d, want 1", len(got))
	}
}

func TestStaleClaimCannotOverwriteANewerClaim(t *testing.T) {
	h := newHarness(t)
	target := h.addDestination("iPhone")
	eventID := h.addTestEvent(target, time.Now())
	s := h.notifier.Store
	if _, err := s.FanOut(h.ctx, events.Delivered, 20); err != nil {
		t.Fatal(err)
	}

	first, err := s.ClaimDue(h.ctx, 20, time.Minute)
	if err != nil || len(first) != 1 {
		t.Fatalf("first claim: %v, %d", err, len(first))
	}
	// A claimed delivery is invisible to other workers while its lease holds.
	if again, _ := s.ClaimDue(h.ctx, 20, time.Minute); len(again) != 0 {
		t.Fatalf("leased delivery was claimed twice")
	}
	// The first worker stalls past its lease; another takes the delivery over.
	if _, err := h.pool.Exec(h.ctx,
		`UPDATE deliveries SET locked_until = now() - interval '1 second' WHERE event_id = $1`,
		eventID); err != nil {
		t.Fatal(err)
	}
	second, err := s.ClaimDue(h.ctx, 20, time.Minute)
	if err != nil || len(second) != 1 || second[0].Token == first[0].Token {
		t.Fatalf("takeover claim: %v, %+v", err, second)
	}

	if err := s.Record(h.ctx, first[0], store.StatusFailed, "late"); !errors.Is(err, store.ErrStaleClaim) {
		t.Fatalf("stale record err = %v, want ErrStaleClaim", err)
	}
	if err := s.Record(h.ctx, second[0], store.StatusDelivered, ""); err != nil {
		t.Fatal(err)
	}
	if got := h.deliveries(eventID); got[0].status != store.StatusDelivered || got[0].attempts != 2 {
		t.Fatalf("delivery = %+v, want delivered after 2 attempts", got[0])
	}
}

func TestTestEventOlderThanTenMinutesExpiresUnsent(t *testing.T) {
	h := newHarness(t)
	target := h.addDestination("iPhone")
	eventID := h.addTestEvent(target, time.Now().Add(-11*time.Minute))

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	if got := h.deliveries(eventID); len(got) != 1 || got[0].status != store.StatusExpired {
		t.Fatalf("deliveries = %+v, want one expired", got)
	}
	if n := len(h.push.requests()); n != 0 {
		t.Fatalf("expired event was sent %d times", n)
	}
}

func TestRejectedPushIsRecordedAsFailed(t *testing.T) {
	h := newHarness(t)
	h.push.status = http.StatusBadRequest
	target := h.addDestination("iPhone")
	eventID := h.addTestEvent(target, time.Now())

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	got := h.deliveries(eventID)
	if len(got) != 1 || got[0].status != store.StatusFailed || got[0].lastError == nil ||
		!strings.Contains(*got[0].lastError, "400") {
		t.Fatalf("deliveries = %+v, want failed with the 400 recorded", got)
	}
}

func TestDisabledDestinationGetsNoDelivery(t *testing.T) {
	h := newHarness(t)
	target := h.addDestination("iPhone")
	if _, err := h.pool.Exec(h.ctx,
		`UPDATE destinations SET disabled_at = now(), disabled_reason = 'user_removed' WHERE id = $1`,
		target); err != nil {
		t.Fatal(err)
	}
	eventID := h.addTestEvent(target, time.Now())

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	if got := h.deliveries(eventID); len(got) != 0 {
		t.Fatalf("disabled destination got deliveries: %+v", got)
	}
}

// runInBackground starts Run with the given sweep and stops it at test end.
func (h *harness) runInBackground(sweep time.Duration) {
	h.t.Helper()
	ctx, cancel := context.WithCancel(h.ctx)
	listener, err := store.Listen(ctx, h.url, Channel)
	if err != nil {
		h.t.Fatal(err)
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		h.notifier.Run(ctx, listener, sweep) //nolint:errcheck // stopped by cancel
	}()
	h.t.Cleanup(func() {
		cancel()
		<-done
		listener.Close(context.Background()) //nolint:errcheck // test cleanup
	})
}

func (h *harness) waitForStatus(eventID, status string, within time.Duration) {
	h.t.Helper()
	deadline := time.Now().Add(within)
	for time.Now().Before(deadline) {
		if got := h.deliveries(eventID); len(got) == 1 && got[0].status == status {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	h.t.Fatalf("event %s not %s within %s: %+v", eventID, status, within, h.deliveries(eventID))
}

func TestNotifyWakesTheNotifierWithoutWaitingForTheSweep(t *testing.T) {
	h := newHarness(t)
	target := h.addDestination("iPhone")
	h.runInBackground(time.Hour) // the sweep can never be what delivers this
	time.Sleep(200 * time.Millisecond)

	eventID := h.addTestEvent(target, time.Now())

	h.waitForStatus(eventID, store.StatusDelivered, 3*time.Second)
}

func TestSweepDeliversAnEventWhoseNotifyWasMissed(t *testing.T) {
	h := newHarness(t)
	target := h.addDestination("iPhone")
	if _, err := h.pool.Exec(h.ctx,
		`ALTER TABLE public_events DISABLE TRIGGER public_events_notify`); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		h.pool.Exec(context.Background(), //nolint:errcheck // test cleanup
			`ALTER TABLE public_events ENABLE TRIGGER public_events_notify`)
	})
	h.runInBackground(300 * time.Millisecond)
	time.Sleep(100 * time.Millisecond)

	eventID := h.addTestEvent(target, time.Now())

	h.waitForStatus(eventID, store.StatusDelivered, 3*time.Second)
}
