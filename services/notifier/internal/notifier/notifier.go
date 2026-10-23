// Package notifier runs the delivery loop: wake on NOTIFY or on the sweep
// timer, fan the outbox out into deliveries, then claim, send and record.
package notifier

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
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
		n.record(ctx, log, claim, store.StatusFailed, err.Error())
		return
	}

	// Never hold the claim past its lease: a send that outlives it could race
	// a worker that has already taken the delivery over.
	sendCtx, cancel := context.WithDeadline(ctx, claim.LockedUntil)
	defer cancel()
	result, err := n.Sender.Send(sendCtx, push.Subscription{
		Endpoint: claim.Endpoint, P256dh: claim.P256dh, Auth: claim.Auth,
	}, notification, remaining)

	switch {
	case err != nil:
		// Retries with backoff arrive with "Delivery resilience" (#73).
		n.record(ctx, log, claim, store.StatusFailed, err.Error())
	case result.StatusCode >= 200 && result.StatusCode < 300:
		n.record(ctx, log, claim, store.StatusDelivered, "")
	default:
		n.record(ctx, log, claim, store.StatusFailed,
			fmt.Sprintf("push service answered %d: %s", result.StatusCode, result.Body))
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
