// Package notifier runs the delivery loop: wake on NOTIFY or on the sweep
// timer, fan the outbox out into deliveries, then claim, send and record.
package notifier

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/events"
	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/push"
	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/store"
)

// Channel is the NOTIFY channel the public_events insert trigger signals.
const Channel = "public_events"

// Notifier delivers public events.
type Notifier struct {
	Store     *store.Store
	Sender    push.Sender
	Log       *slog.Logger
	BatchSize int
	Lease     time.Duration
	Now       func() time.Time
	// AppOrigin is the PWA's origin; notification links are absolute under it.
	AppOrigin string
	// Jitter returns a value in [0, 1) that spreads retries out (rand.Float64).
	Jitter func() float64
}

// Retry delays grow from retryBase, doubling per attempt, up to retryCap.
const (
	retryBase = 10 * time.Second
	retryCap  = 15 * time.Minute
)

// backoff is the delay before the attempt after `attempts` failed ones:
// exponential, capped, with "equal jitter" so it is never shorter than half
// the step. jitter is in [0, 1).
func backoff(attempts int, jitter float64) time.Duration {
	step := retryCap
	if shift := attempts - 1; shift < 32 && retryBase<<shift < retryCap {
		step = retryBase << shift
	}
	return step/2 + time.Duration(jitter*float64(step/2))
}

// RunOnce fans out every pending event, then works every due delivery. It is
// the whole unit of work; the wake-up strategy lives in Run.
func (n *Notifier) RunOnce(ctx context.Context) error {
	for {
		dispatched, err := n.Store.FanOut(ctx, events.Delivered, n.BatchSize)
		if err != nil {
			return err
		}
		if dispatched > 0 {
			n.Log.Info("outbox.fanned_out", "events", dispatched)
		}
		if dispatched < n.BatchSize {
			break
		}
	}

	for {
		claims, err := n.Store.ClaimDue(ctx, n.BatchSize, n.Lease)
		if err != nil {
			return err
		}
		for _, claim := range claims {
			if ctx.Err() != nil {
				// Shutting down: unsent claims come back when their lease runs out.
				return ctx.Err()
			}
			n.deliver(ctx, claim)
		}
		if len(claims) < n.BatchSize {
			return nil
		}
	}
}

func (n *Notifier) deliver(ctx context.Context, claim store.Claim) {
	log := n.Log.With("delivery_id", claim.DeliveryID, "event_id", claim.Event.ID,
		"type", claim.Event.Type, "destination_id", claim.DestinationID)

	remaining := events.ExpiresAt(claim.Event).Sub(n.Now())
	if remaining <= 0 {
		n.record(ctx, log, claim, store.StatusExpired, "past its expiry before send")
		return
	}

	notification, err := events.Render(claim.Event, claim.Label, n.AppOrigin)
	if err != nil {
		log.Warn("delivery.render_failed", "error", err)
		n.record(ctx, log, claim, store.StatusFailed, "event could not be rendered")
		return
	}

	// Never hold the claim past its lease: a send that outlives it could race
	// a worker that has already taken the delivery over.
	sendCtx, cancel := context.WithDeadline(ctx, claim.LockedUntil)
	defer cancel()
	result, err := n.Sender.Send(sendCtx, push.Subscription{
		Endpoint: claim.Endpoint, P256dh: claim.P256dh, Auth: claim.Auth,
	}, notification, remaining)

	switch code := result.StatusCode; {
	case ctx.Err() != nil:
		// Shutting down mid-send: record nothing, exactly as if the process had
		// died. Another worker retries once the lease runs out.
		log.Info("delivery.abandoned_on_shutdown")
	case err != nil && errors.Is(sendCtx.Err(), context.DeadlineExceeded):
		// The lease ran out before an answer came. Record nothing, as on
		// shutdown: the claim may already be another worker's, and lease
		// recovery sends it again without a backoff.
		log.Warn("delivery.lease_ran_out", "attempts", claim.Attempts)
	case errors.Is(err, push.ErrUnsendable):
		n.record(ctx, log, claim, store.StatusFailed, err.Error())
	case err != nil:
		log.Warn("delivery.send_failed", "error", err)
		n.retry(ctx, log, claim, sendFailure(err))
	case code >= 200 && code < 300:
		n.record(ctx, log, claim, store.StatusDelivered, "")
	case code == http.StatusNotFound || code == http.StatusGone:
		n.record(ctx, log, claim, store.StatusGone, pushAnswer(result))
	case code == http.StatusTooManyRequests || code >= 500:
		n.retry(ctx, log, claim, pushAnswer(result))
	default:
		n.record(ctx, log, claim, store.StatusFailed, pushAnswer(result))
	}
}

// Errors are stored in last_error, which the delivery log shows the operator.
// They never carry the push address (the endpoint URL) or the push service's
// answer body: a status code and a short reason only.

func pushAnswer(result push.Result) string {
	return fmt.Sprintf("push service answered %d %s",
		result.StatusCode, http.StatusText(result.StatusCode))
}

// sendFailure names a failed send by kind. The error itself quotes the
// endpoint URL ("Post \"https://...\": ..."), so it only goes to the log.
func sendFailure(err error) string {
	var opErr *net.OpError
	switch {
	case errors.Is(err, context.DeadlineExceeded) || os.IsTimeout(err):
		return "network error: timed out"
	case errors.As(err, &opErr):
		return "network error: " + opErr.Op + " failed"
	default:
		return "network error"
	}
}

// retry schedules another attempt with backoff, or gives up as expired when
// that attempt would land past the event's max age (ADR-015).
func (n *Notifier) retry(ctx context.Context, log *slog.Logger, claim store.Claim, reason string) {
	delay := backoff(claim.Attempts, n.Jitter())
	if !n.Now().Add(delay).Before(events.ExpiresAt(claim.Event)) {
		n.record(ctx, log, claim, store.StatusExpired, "gave up: "+reason)
		return
	}
	err := n.Store.Retry(ctx, claim, delay, reason)
	switch {
	case errors.Is(err, store.ErrStaleClaim):
		log.Warn("delivery.stale_claim_dropped", "status", store.StatusPending)
	case err != nil:
		log.Error("delivery.retry_failed", "error", err)
	default:
		log.Warn("delivery.retrying", "attempts", claim.Attempts, "in", delay.String(), "reason", reason)
	}
}

func (n *Notifier) record(ctx context.Context, log *slog.Logger, claim store.Claim, status, reason string) {
	err := n.Store.Record(ctx, claim, status, reason)
	switch {
	case errors.Is(err, store.ErrStaleClaim):
		log.Warn("delivery.stale_claim_dropped", "status", status)
	case err != nil:
		log.Error("delivery.record_failed", "status", status, "error", err)
	case status == store.StatusDelivered:
		log.Info("delivery.delivered", "attempts", claim.Attempts)
	default:
		log.Warn("delivery.not_delivered", "status", status, "reason", reason)
	}
}

// Run loops until ctx ends: work, then wait for a NOTIFY or the sweep timer,
// whichever comes first. The sweep catches notifications missed while the
// listener was down and deliveries that have come due.
func (n *Notifier) Run(ctx context.Context, listener *pgx.Conn, sweep time.Duration) error {
	for {
		if err := n.RunOnce(ctx); err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			n.Log.Error("notifier.cycle_failed", "error", err)
		}

		waitCtx, cancel := context.WithTimeout(ctx, sweep)
		notification, err := listener.WaitForNotification(waitCtx)
		cancel()
		switch {
		case ctx.Err() != nil:
			return ctx.Err()
		case err == nil:
			n.Log.Debug("notifier.woken", "event_id", notification.Payload)
		case errors.Is(err, context.DeadlineExceeded):
			// Sweep tick.
		default:
			return fmt.Errorf("waiting for notification: %w", err)
		}
	}
}
