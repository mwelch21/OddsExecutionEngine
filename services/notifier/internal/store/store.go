// Package store is the notifier's only access to Postgres: fan-out of the
// public outbox into deliveries, claiming due deliveries, and recording what
// happened (ADR-015). Alembic owns the schema; this package never changes it.
package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/events"
)

// Delivery statuses, matching the deliveries.status column.
const (
	StatusPending   = "pending"
	StatusDelivered = "delivered"
	StatusFailed    = "failed"
	StatusExpired   = "expired"
)

// ErrStaleClaim means the claim token no longer matches: the lease ran out and
// another worker claimed the delivery. The result must be dropped.
var ErrStaleClaim = errors.New("claim token no longer matches")

// Store wraps a pgx pool.
type Store struct {
	pool *pgxpool.Pool
}

// New returns a Store over an open pool.
func New(pool *pgxpool.Pool) *Store {
	return &Store{pool: pool}
}

// FanOut expands undispatched outbox rows of the given types into deliveries
// and marks them dispatched. Delivery rows are inserted with ON CONFLICT DO
// NOTHING under UNIQUE(event_id, destination_id), so a fan-out interrupted by
// a crash is safe to redo. `dispatched_at` means fan-out is complete, never
// "delivered". Returns the number of events dispatched.
func (s *Store) FanOut(ctx context.Context, types []string, limit int) (int, error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return 0, fmt.Errorf("beginning fan-out: %w", err)
	}
	defer tx.Rollback(ctx) //nolint:errcheck // no-op after commit

	rows, err := tx.Query(ctx, `
		SELECT id, type, payload::text
		FROM public_events
		WHERE dispatched_at IS NULL AND type = ANY($1)
		ORDER BY created_at
		LIMIT $2
		FOR UPDATE SKIP LOCKED`, types, limit)
	if err != nil {
		return 0, fmt.Errorf("selecting undispatched events: %w", err)
	}
	type pending struct {
		id, eventType, subject string
	}
	var batch []pending
	for rows.Next() {
		var p pending
		var payload string
		if err := rows.Scan(&p.id, &p.eventType, &payload); err != nil {
			rows.Close()
			return 0, fmt.Errorf("scanning outbox row: %w", err)
		}
		var envelope events.CloudEvent
		if err := json.Unmarshal([]byte(payload), &envelope); err != nil {
			rows.Close()
			return 0, fmt.Errorf("decoding outbox row %s: %w", p.id, err)
		}
		p.subject = envelope.Subject
		batch = append(batch, p)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, fmt.Errorf("reading outbox rows: %w", err)
	}

	for _, p := range batch {
		if events.Targeted(p.eventType) {
			// Exactly one delivery, for the destination named in the subject,
			// and only while it is active.
			_, err = tx.Exec(ctx, `
				INSERT INTO deliveries (id, event_id, destination_id)
				SELECT $1, $2, d.id FROM destinations d
				WHERE d.id = $3 AND d.disabled_at IS NULL
				ON CONFLICT (event_id, destination_id) DO NOTHING`,
				uuid.NewString(), p.id, p.subject)
		} else {
			_, err = tx.Exec(ctx, `
				INSERT INTO deliveries (id, event_id, destination_id)
				SELECT gen_random_uuid()::text, $1, d.id FROM destinations d
				WHERE d.disabled_at IS NULL
				ON CONFLICT (event_id, destination_id) DO NOTHING`, p.id)
		}
		if err != nil {
			return 0, fmt.Errorf("fanning out event %s: %w", p.id, err)
		}
		if _, err := tx.Exec(ctx,
			`UPDATE public_events SET dispatched_at = now() WHERE id = $1`, p.id); err != nil {
			return 0, fmt.Errorf("marking event %s dispatched: %w", p.id, err)
		}
	}

	if err := tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("committing fan-out: %w", err)
	}
	return len(batch), nil
}

// Claim is one delivery a worker now owns until LockedUntil.
type Claim struct {
	DeliveryID    string
	Token         string
	Attempts      int
	LockedUntil   time.Time
	Event         events.CloudEvent
	DestinationID string
	Label         string
	Endpoint      string
	P256dh        string
	Auth          string
}

// ClaimDue claims up to limit due deliveries. SKIP LOCKED keeps two workers
// off the same row; the lease lets another worker recover a claim whose
// holder died; each claim gets a fresh token. The claim commits here, before
// any network call, so no row lock is held while the push service answers.
func (s *Store) ClaimDue(ctx context.Context, limit int, lease time.Duration) ([]Claim, error) {
	rows, err := s.pool.Query(ctx, `
		WITH due AS (
			SELECT id FROM deliveries
			WHERE status = 'pending'
			  AND next_attempt_at <= now()
			  AND (locked_until IS NULL OR locked_until < now())
			ORDER BY next_attempt_at
			LIMIT $1
			FOR UPDATE SKIP LOCKED
		)
		UPDATE deliveries d
		SET locked_until = now() + make_interval(secs => $2),
		    claim_token = gen_random_uuid()::text,
		    attempts = d.attempts + 1
		FROM due, public_events e, destinations t
		WHERE d.id = due.id AND e.id = d.event_id AND t.id = d.destination_id
		RETURNING d.id, d.claim_token, d.attempts, d.locked_until,
		          e.payload::text, t.id, t.label, t.address,
		          coalesce(t.config->>'p256dh', ''), coalesce(t.config->>'auth', '')`,
		limit, lease.Seconds())
	if err != nil {
		return nil, fmt.Errorf("claiming due deliveries: %w", err)
	}
	defer rows.Close()

	var claims []Claim
	for rows.Next() {
		var c Claim
		var payload string
		if err := rows.Scan(&c.DeliveryID, &c.Token, &c.Attempts, &c.LockedUntil,
			&payload, &c.DestinationID, &c.Label, &c.Endpoint, &c.P256dh, &c.Auth); err != nil {
			return nil, fmt.Errorf("scanning claim: %w", err)
		}
		if err := json.Unmarshal([]byte(payload), &c.Event); err != nil {
			return nil, fmt.Errorf("decoding event for delivery %s: %w", c.DeliveryID, err)
		}
		claims = append(claims, c)
	}
	return claims, rows.Err()
}

// Record stores a final outcome, but only while the claim token still
// matches. A worker whose lease expired gets ErrStaleClaim and must drop its
// result, so it can never overwrite a newer worker's outcome.
func (s *Store) Record(ctx context.Context, claim Claim, status, lastError string) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("beginning record: %w", err)
	}
	defer tx.Rollback(ctx) //nolint:errcheck // no-op after commit

	var errText *string
	if lastError != "" {
		errText = &lastError
	}
	tag, err := tx.Exec(ctx, `
		UPDATE deliveries
		SET status = $3::text,
		    delivered_at = CASE WHEN $3::text = 'delivered' THEN now() END,
		    last_error = $4::text,
		    locked_until = NULL
		WHERE id = $1 AND claim_token = $2 AND status = 'pending'`,
		claim.DeliveryID, claim.Token, status, errText)
	if err != nil {
		return fmt.Errorf("recording delivery %s: %w", claim.DeliveryID, err)
	}
	if tag.RowsAffected() == 0 {
		return ErrStaleClaim
	}
	if status == StatusDelivered {
		// Convenience only: deliveries stay the source of truth.
		if _, err := tx.Exec(ctx,
			`UPDATE destinations SET last_delivered_at = now() WHERE id = $1`,
			claim.DestinationID); err != nil {
			return fmt.Errorf("stamping destination %s: %w", claim.DestinationID, err)
		}
	}
	return tx.Commit(ctx)
}

// Listen opens a dedicated connection subscribed to the outbox channel.
func Listen(ctx context.Context, databaseURL, channel string) (*pgx.Conn, error) {
	conn, err := pgx.Connect(ctx, databaseURL)
	if err != nil {
		return nil, fmt.Errorf("connecting listener: %w", err)
	}
	if _, err := conn.Exec(ctx, "LISTEN "+pgx.Identifier{channel}.Sanitize()); err != nil {
		conn.Close(ctx) //nolint:errcheck // already failing
		return nil, fmt.Errorf("listening on %s: %w", channel, err)
	}
	return conn, nil
}
