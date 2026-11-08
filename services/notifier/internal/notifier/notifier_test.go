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
	mathrand "math/rand/v2"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
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
	// script answers the next requests in order, before falling back to status.
	// fakeDrop closes the connection without answering: a network error.
	script []int
	// delay holds every answer back, widening any window for a double send.
	delay time.Duration
	// body is written with every answer.
	body string
}

const fakeDrop = -1

func newFakePushService(t *testing.T) *fakePushService {
	f := &fakePushService{status: http.StatusCreated}
	f.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body) //nolint:errcheck // test server
		f.mu.Lock()
		f.hits = append(f.hits, r)
		status := f.status
		if len(f.script) > 0 {
			status, f.script = f.script[0], f.script[1:]
		}
		delay, body := f.delay, f.body
		f.mu.Unlock()
		select {
		case <-time.After(delay):
		case <-r.Context().Done():
			return
		}
		if status == fakeDrop {
			conn, _, _ := w.(http.Hijacker).Hijack()
			conn.Close()
			return
		}
		w.WriteHeader(status)
		io.WriteString(w, body) //nolint:errcheck // test server
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
			Jitter:    mathrand.Float64,
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
	return h.addOpportunityEventWith(at, expiresAt, func(map[string]any) {})
}

// addOpportunityEventWith lets a test change the event's data before it is written.
func (h *harness) addOpportunityEventWith(at, expiresAt time.Time, edit func(data map[string]any)) string {
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
	edit(payload["data"].(map[string]any))
	body, _ := json.Marshal(payload)
	if _, err := h.pool.Exec(h.ctx,
		`INSERT INTO public_events (id, type, payload) VALUES ($1, $2, $3::json)`,
		id, events.TypeOpportunityIdentifiedV1, string(body)); err != nil {
		h.t.Fatal(err)
	}
	return id
}

func (h *harness) addQuotaWarningEvent(at time.Time) string {
	h.t.Helper()
	raw, err := os.ReadFile("../../../../contracts/events/examples/" + events.TypeQuotaWarningV1 + ".json")
	if err != nil {
		h.t.Fatal(err)
	}
	var payload map[string]any
	if err := json.Unmarshal(raw, &payload); err != nil {
		h.t.Fatal(err)
	}
	id := uuid.NewString()
	payload["id"], payload["time"] = id, at.Format(time.RFC3339Nano)
	body, _ := json.Marshal(payload)
	if _, err := h.pool.Exec(h.ctx,
		`INSERT INTO public_events (id, type, payload) VALUES ($1, $2, $3::json)`,
		id, events.TypeQuotaWarningV1, string(body)); err != nil {
		h.t.Fatal(err)
	}
	return id
}

type deliveryRow struct {
	destinationID, status string
	attempts              int
	lastError             *string
	endedAt               *time.Time
}

func (h *harness) deliveries(eventID string) []deliveryRow {
	h.t.Helper()
	rows, err := h.pool.Query(h.ctx,
		`SELECT destination_id, status, attempts, last_error, ended_at FROM deliveries WHERE event_id = $1`,
		eventID)
	if err != nil {
		h.t.Fatal(err)
	}
	defer rows.Close()
	var out []deliveryRow
	for rows.Next() {
		var r deliveryRow
		if err := rows.Scan(&r.destinationID, &r.status, &r.attempts, &r.lastError, &r.endedAt); err != nil {
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

// Single operator today, so the operator's audience is every active destination.
func TestQuotaWarningReachesEveryOperatorDestination(t *testing.T) {
	h := newHarness(t)
	phone := h.addDestination("iPhone")
	mac := h.addDestination("Mac")
	eventID := h.addQuotaWarningEvent(time.Now())

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	got := map[string]string{}
	for _, d := range h.deliveries(eventID) {
		got[d.destinationID] = d.status
	}
	if len(got) != 2 || got[phone] != store.StatusDelivered || got[mac] != store.StatusDelivered {
		t.Fatalf("deliveries = %v, want delivered to both operator destinations", got)
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

func (h *harness) markRemoved(destinationID string) {
	h.t.Helper()
	if _, err := h.pool.Exec(h.ctx, `
		UPDATE destinations SET disabled_at = now(), disabled_reason = 'user_removed'
		WHERE id = $1`, destinationID); err != nil {
		h.t.Fatal(err)
	}
}

func (h *harness) reEnable(destinationID string) {
	h.t.Helper()
	if _, err := h.pool.Exec(h.ctx, `
		UPDATE destinations SET disabled_at = NULL, disabled_reason = NULL WHERE id = $1`,
		destinationID); err != nil {
		h.t.Fatal(err)
	}
}

func TestPendingDeliveryWaitsWhileItsDestinationIsRemoved(t *testing.T) {
	h := newHarness(t)
	h.push.script = []int{http.StatusServiceUnavailable}
	target := h.addDestination("iPhone")
	eventID := h.addTestEvent(target, time.Now())
	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	h.markRemoved(target)
	h.makeDue()
	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}
	if got := h.deliveries(eventID); len(got) != 1 || got[0].status != store.StatusPending ||
		got[0].attempts != 1 {
		t.Fatalf("deliveries = %+v, want one pending, still on its first attempt", got)
	}
	if n := len(h.push.requests()); n != 1 {
		t.Fatalf("removed destination was sent to: %d requests, want 1", n)
	}

	h.reEnable(target)
	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}
	if got := h.deliveries(eventID); len(got) != 1 || got[0].status != store.StatusDelivered {
		t.Fatalf("deliveries = %+v, want delivered once re-enabled", got)
	}
}

func TestPendingDeliveryThatAgedOutWhileRemovedExpiresOnReEnable(t *testing.T) {
	h := newHarness(t)
	target := h.addDestination("iPhone")
	h.markRemoved(target)
	eventID := h.addTestEvent(target, time.Now().Add(-11*time.Minute))
	// Queued before the removal, so fan-out's active filter did not apply.
	if _, err := h.pool.Exec(h.ctx, `
		INSERT INTO deliveries (id, event_id, destination_id) VALUES ($1, $2, $3)`,
		uuid.NewString(), eventID, target); err != nil {
		t.Fatal(err)
	}

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}
	if got := h.deliveries(eventID); len(got) != 1 || got[0].status != store.StatusPending {
		t.Fatalf("deliveries = %+v, want one pending while removed", got)
	}

	h.reEnable(target)
	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}
	if got := h.deliveries(eventID); len(got) != 1 || got[0].status != store.StatusExpired {
		t.Fatalf("deliveries = %+v, want expired after re-enable", got)
	}
	if n := len(h.push.requests()); n != 0 {
		t.Fatalf("stale delivery was sent %d times", n)
	}
}

func TestRejectionDuringASendMarksARemovedDestinationGone(t *testing.T) {
	h := newHarness(t)
	target := h.addDestination("iPhone")
	h.addTestEvent(target, time.Now())
	if _, err := h.notifier.Store.FanOut(h.ctx, events.Delivered, 10); err != nil {
		t.Fatal(err)
	}
	claims, err := h.notifier.Store.ClaimDue(h.ctx, 10, time.Minute)
	if err != nil || len(claims) != 1 {
		t.Fatalf("claims = %d, err = %v; want one", len(claims), err)
	}

	// The operator removes the device while its push is in flight, then the
	// push service answers 410.
	h.markRemoved(target)
	if err := h.notifier.Store.Record(h.ctx, claims[0], store.StatusGone, "410"); err != nil {
		t.Fatal(err)
	}

	var reason string
	if err := h.pool.QueryRow(h.ctx,
		`SELECT disabled_reason FROM destinations WHERE id = $1`, target).Scan(&reason); err != nil {
		t.Fatal(err)
	}
	// `gone` is what makes the API refuse a re-enable (409).
	if reason != "gone" {
		t.Fatalf("disabled_reason = %q, want gone", reason)
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

type retryRow struct {
	status         string
	attempts       int
	lastError      *string
	dueIn          time.Duration
	lockedUntilSet bool
}

func (h *harness) retryState(eventID string) retryRow {
	h.t.Helper()
	var r retryRow
	var dueInSeconds float64
	if err := h.pool.QueryRow(h.ctx, `
		SELECT status, attempts, last_error,
		       extract(epoch FROM next_attempt_at - now())::float8,
		       locked_until IS NOT NULL
		FROM deliveries WHERE event_id = $1`, eventID).Scan(
		&r.status, &r.attempts, &r.lastError, &dueInSeconds, &r.lockedUntilSet); err != nil {
		h.t.Fatal(err)
	}
	r.dueIn = time.Duration(dueInSeconds * float64(time.Second))
	return r
}

// makeDue fast-forwards every pending delivery's retry to now.
func (h *harness) makeDue() {
	h.t.Helper()
	if _, err := h.pool.Exec(h.ctx,
		`UPDATE deliveries SET next_attempt_at = now() WHERE status = 'pending'`); err != nil {
		h.t.Fatal(err)
	}
}

func TestTransientAnswersAreRetriedWithBackoffUntilDelivered(t *testing.T) {
	for name, answer := range map[string]int{
		"429": http.StatusTooManyRequests, "503": http.StatusServiceUnavailable,
		"network error": fakeDrop,
	} {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t)
			h.push.script = []int{answer}
			target := h.addDestination("iPhone")
			eventID := h.addTestEvent(target, time.Now())

			if err := h.notifier.RunOnce(h.ctx); err != nil {
				t.Fatal(err)
			}
			got := h.retryState(eventID)
			if got.status != store.StatusPending || got.attempts != 1 || got.lastError == nil ||
				got.lockedUntilSet || got.dueIn <= 0 {
				t.Fatalf("after a transient answer: %+v, want pending, unlocked, due later, error kept", got)
			}

			// Not due yet: a second cycle must not send again.
			if err := h.notifier.RunOnce(h.ctx); err != nil {
				t.Fatal(err)
			}
			if n := len(h.push.requests()); n != 1 {
				t.Fatalf("push service saw %d requests before the retry was due, want 1", n)
			}

			h.makeDue()
			if err := h.notifier.RunOnce(h.ctx); err != nil {
				t.Fatal(err)
			}
			if got := h.deliveries(eventID); got[0].status != store.StatusDelivered || got[0].attempts != 2 {
				t.Fatalf("after the retry: %+v, want delivered on attempt 2", got[0])
			}
		})
	}
}

func TestGoneSubscriptionDisablesTheDestinationAndItsPendingDeliveries(t *testing.T) {
	for name, answer := range map[string]int{"404": http.StatusNotFound, "410": http.StatusGone} {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t)
			h.push.status = answer
			phone := h.addDestination("iPhone")
			mac := h.addDestination("Mac")
			// BatchSize 1 keeps the phone's second delivery queued behind the first
			// answer, so it is pending when the phone turns out to be gone.
			h.notifier.BatchSize = 1
			first := h.addTestEvent(phone, time.Now())
			second := h.addTestEvent(phone, time.Now())
			if err := h.notifier.RunOnce(h.ctx); err != nil {
				t.Fatal(err)
			}

			for _, eventID := range []string{first, second} {
				if got := h.deliveries(eventID); got[0].status != store.StatusGone {
					t.Fatalf("delivery of %s = %+v, want gone", eventID, got[0])
				}
			}
			if n := len(h.push.requests()); n != 1 {
				t.Fatalf("push service saw %d requests, want 1: the rest were never sent", n)
			}
			var reason *string
			h.pool.QueryRow(h.ctx, `SELECT disabled_reason FROM destinations WHERE id = $1 AND disabled_at IS NOT NULL`,
				phone).Scan(&reason) //nolint:errcheck // asserted below
			if reason == nil || *reason != "gone" {
				t.Fatalf("phone disabled_reason = %v, want gone", reason)
			}

			// A later event skips the gone phone and still reaches the Mac.
			h.push.status = http.StatusCreated
			later := h.addOpportunityEvent(time.Now(), time.Now().Add(time.Hour))
			h.notifier.BatchSize = 20
			if err := h.notifier.RunOnce(h.ctx); err != nil {
				t.Fatal(err)
			}
			if got := h.deliveries(later); len(got) != 1 || got[0].destinationID != mac {
				t.Fatalf("later deliveries = %+v, want only the Mac", got)
			}
		})
	}
}

// A notification too big for Web Push will never fit: failed, not retried.
func TestOversizedNotificationFailsWithoutRetrying(t *testing.T) {
	h := newHarness(t)
	h.addDestination("iPhone")
	eventID := h.addOpportunityEventWith(time.Now(), time.Now().Add(time.Hour), func(data map[string]any) {
		data["selection"] = strings.Repeat("new york knicks ", 300)
	})

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	got := h.deliveries(eventID)
	if len(got) != 1 || got[0].status != store.StatusFailed || got[0].lastError == nil ||
		!strings.Contains(*got[0].lastError, "limit") {
		t.Fatalf("deliveries = %+v, want failed over the size limit", got)
	}
	if n := len(h.push.requests()); n != 0 {
		t.Fatalf("oversized notification was sent %d times", n)
	}
}

// The shortest retry (5s) lands past this test event's 10-minute max age, so
// the notifier gives up now instead of scheduling a send nobody wants.
func TestRetryThatWouldLandPastMaxAgeExpires(t *testing.T) {
	h := newHarness(t)
	h.push.status = http.StatusServiceUnavailable
	target := h.addDestination("iPhone")
	eventID := h.addTestEvent(target, time.Now().Add(-10*time.Minute+2*time.Second))

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	got := h.deliveries(eventID)
	if len(got) != 1 || got[0].status != store.StatusExpired || got[0].lastError == nil ||
		!strings.Contains(*got[0].lastError, "503") {
		t.Fatalf("deliveries = %+v, want expired with the 503 kept", got)
	}
}

// A notifier killed mid-send records nothing and leaves only its lease
// behind. Once the lease runs out, a restarted notifier sends it.
func TestDeliveryInFlightWhenTheNotifierIsKilledIsRetriedAfterItsLease(t *testing.T) {
	h := newHarness(t)
	h.push.delay = time.Hour // the first send never answers
	target := h.addDestination("iPhone")
	eventID := h.addTestEvent(target, time.Now())

	doomed := *h.notifier
	doomed.Lease = time.Second
	ctx, kill := context.WithCancel(h.ctx)
	done := make(chan error)
	go func() { done <- doomed.RunOnce(ctx) }()
	for len(h.push.requests()) == 0 {
		time.Sleep(10 * time.Millisecond)
	}
	kill()
	<-done
	if got := h.retryState(eventID); got.status != store.StatusPending || got.lastError != nil {
		t.Fatalf("after the kill: %+v, want pending with nothing recorded", got)
	}

	h.push.delay = 0
	// Restarted inside the lease: the claim still belongs to the dead worker.
	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}
	if n := len(h.push.requests()); n != 1 {
		t.Fatalf("delivery under a live lease was sent again (%d requests)", n)
	}

	time.Sleep(1100 * time.Millisecond)
	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}
	if got := h.deliveries(eventID); got[0].status != store.StatusDelivered || got[0].attempts != 2 {
		t.Fatalf("delivery = %+v, want delivered on attempt 2", got[0])
	}
}

// A retry scheduled before the notifier stopped, still pending when it comes
// back past the event's max age, expires instead of sending stale news.
func TestRetryThatAgedOutWhileTheNotifierWasStoppedExpiresOnRestart(t *testing.T) {
	h := newHarness(t)
	h.push.script = []int{http.StatusServiceUnavailable}
	target := h.addDestination("iPhone")
	eventID := h.addTestEvent(target, time.Now())
	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	restartedAt := time.Now().Add(11 * time.Minute)
	h.notifier.Now = func() time.Time { return restartedAt }
	h.makeDue()
	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	if got := h.deliveries(eventID); got[0].status != store.StatusExpired {
		t.Fatalf("delivery = %+v, want expired", got[0])
	}
	if n := len(h.push.requests()); n != 1 {
		t.Fatalf("push service saw %d requests, want only the first attempt", n)
	}
}

func TestTwoNotifiersNeverSendTheSameDelivery(t *testing.T) {
	h := newHarness(t)
	h.push.delay = 20 * time.Millisecond
	destinations := []string{h.addDestination("iPhone"), h.addDestination("Mac")}
	var eventIDs []string
	for range 15 {
		eventIDs = append(eventIDs, h.addOpportunityEvent(time.Now(), time.Now().Add(time.Hour)))
	}

	other := *h.notifier
	h.notifier.BatchSize, other.BatchSize = 3, 3
	var wg sync.WaitGroup
	for _, n := range []*Notifier{h.notifier, &other} {
		wg.Go(func() {
			if err := n.RunOnce(h.ctx); err != nil {
				t.Error(err)
			}
		})
	}
	wg.Wait()

	want := len(destinations) * len(eventIDs)
	if n := len(h.push.requests()); n != want {
		t.Fatalf("push service saw %d requests, want exactly %d", n, want)
	}
	for _, eventID := range eventIDs {
		for _, d := range h.deliveries(eventID) {
			if d.status != store.StatusDelivered || d.attempts != 1 {
				t.Fatalf("delivery = %+v, want delivered on the one attempt", d)
			}
		}
	}
}

// Keys that are not a P-256 point and a 16-byte secret can never encrypt:
// failed at once, not retried for the event's whole max age.
func TestSubscriptionWithBrokenKeysFailsWithoutRetrying(t *testing.T) {
	h := newHarness(t)
	target := h.addDestination("iPhone")
	if _, err := h.pool.Exec(h.ctx,
		`UPDATE destinations SET config = '{"p256dh": "bm90LWEta2V5", "auth": "c2hvcnQ"}'::json WHERE id = $1`,
		target); err != nil {
		t.Fatal(err)
	}
	eventID := h.addTestEvent(target, time.Now())

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	got := h.deliveries(eventID)
	if len(got) != 1 || got[0].status != store.StatusFailed || got[0].lastError == nil ||
		!strings.Contains(*got[0].lastError, "p256dh") {
		t.Fatalf("deliveries = %+v, want failed naming the bad key", got)
	}
	if n := len(h.push.requests()); n != 0 {
		t.Fatalf("broken subscription was sent %d times", n)
	}
}

// A batch shares one lease. Sends the lease cuts off (the slow one, and the
// one queued behind it) are left for lease recovery: no error recorded and no
// backoff, so they go out as soon as the lease is over.
func TestSendsCutOffByTheLeaseAreLeftForLeaseRecovery(t *testing.T) {
	h := newHarness(t)
	h.push.delay = time.Hour
	target := h.addDestination("iPhone")
	first := h.addTestEvent(target, time.Now())
	second := h.addTestEvent(target, time.Now())
	h.notifier.Lease = time.Second

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}
	for _, eventID := range []string{first, second} {
		if got := h.retryState(eventID); got.status != store.StatusPending || got.lastError != nil ||
			got.dueIn > 0 {
			t.Fatalf("after the lease ran out: %+v, want pending, nothing recorded, no backoff", got)
		}
	}

	h.push.delay = 0
	time.Sleep(100 * time.Millisecond) // the lease is already over
	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}
	for _, eventID := range []string{first, second} {
		if got := h.deliveries(eventID); got[0].status != store.StatusDelivered || got[0].attempts != 2 {
			t.Fatalf("delivery of %s = %+v, want delivered on attempt 2", eventID, got[0])
		}
	}
}

// The delivery log shows when each delivery ended, whatever the outcome; a
// delivery still pending, waiting on a retry, has not ended.
func TestEveryFinalStatusStampsWhenTheDeliveryEnded(t *testing.T) {
	cases := map[string]struct {
		answer int
		event  func(h *harness, destinationID string) string
		want   string
	}{
		"delivered": {http.StatusCreated, func(h *harness, d string) string {
			return h.addTestEvent(d, time.Now())
		}, store.StatusDelivered},
		"failed": {http.StatusBadRequest, func(h *harness, d string) string {
			return h.addTestEvent(d, time.Now())
		}, store.StatusFailed},
		"expired": {http.StatusCreated, func(h *harness, d string) string {
			return h.addTestEvent(d, time.Now().Add(-11*time.Minute))
		}, store.StatusExpired},
		"gone": {http.StatusGone, func(h *harness, d string) string {
			return h.addTestEvent(d, time.Now())
		}, store.StatusGone},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t)
			h.push.status = c.answer
			eventID := c.event(h, h.addDestination("iPhone"))
			before := time.Now().Add(-time.Second)

			if err := h.notifier.RunOnce(h.ctx); err != nil {
				t.Fatal(err)
			}

			got := h.deliveries(eventID)
			if len(got) != 1 || got[0].status != c.want {
				t.Fatalf("deliveries = %+v, want one %s", got, c.want)
			}
			if got[0].endedAt == nil || got[0].endedAt.Before(before) {
				t.Fatalf("ended_at = %v, want stamped at the final write", got[0].endedAt)
			}
		})
	}
}

// A gone answer gives up the destination's other pending deliveries too; each
// of those ends then, though it was never sent.
func TestDeliveriesGivenUpForAGoneDestinationAreStampedAsEnded(t *testing.T) {
	h := newHarness(t)
	h.push.status = http.StatusGone
	phone := h.addDestination("iPhone")
	h.notifier.BatchSize = 1
	h.addTestEvent(phone, time.Now())
	queued := h.addTestEvent(phone, time.Now())

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	got := h.deliveries(queued)
	if len(got) != 1 || got[0].status != store.StatusGone || got[0].endedAt == nil {
		t.Fatalf("queued delivery = %+v, want gone with ended_at stamped", got)
	}
}

func TestDeliveryWaitingOnARetryHasNotEnded(t *testing.T) {
	h := newHarness(t)
	h.push.status = http.StatusServiceUnavailable
	eventID := h.addOpportunityEvent(time.Now(), time.Now().Add(time.Hour))
	h.addDestination("iPhone")

	if err := h.notifier.RunOnce(h.ctx); err != nil {
		t.Fatal(err)
	}

	got := h.deliveries(eventID)
	if len(got) != 1 || got[0].status != store.StatusPending || got[0].endedAt != nil {
		t.Fatalf("deliveries = %+v, want pending with no ended_at", got)
	}
}

// The delivery log shows last_error to the operator, so it must never carry
// the push address (the endpoint URL) or whatever the push service answered.
func TestRecordedErrorsNeverCarryThePushAddressOrAnswerBody(t *testing.T) {
	const secret = "tok_SECRET_9f8e7d6c5b4a"
	for name, answer := range map[string]int{
		"failed": http.StatusBadRequest, "gone": http.StatusGone,
		"retried": http.StatusServiceUnavailable, "network error": fakeDrop,
	} {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t)
			h.push.script = []int{answer}
			h.push.body = "rejected " + h.push.server.URL + " " + secret
			eventID := h.addOpportunityEvent(time.Now(), time.Now().Add(time.Hour))
			h.addDestination("iPhone")

			if err := h.notifier.RunOnce(h.ctx); err != nil {
				t.Fatal(err)
			}

			got := h.deliveries(eventID)
			if len(got) != 1 || got[0].lastError == nil {
				t.Fatalf("deliveries = %+v, want one with an error recorded", got)
			}
			text := *got[0].lastError
			for _, leak := range []string{h.push.server.URL, "127.0.0.1", "/push/", secret, "rejected"} {
				if strings.Contains(text, leak) {
					t.Fatalf("last_error %q carries %q", text, leak)
				}
			}
			if answer != fakeDrop && !strings.Contains(text, strconv.Itoa(answer)) {
				t.Fatalf("last_error %q, want the status code kept", text)
			}
		})
	}
}
