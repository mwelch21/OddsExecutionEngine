// Command notifier delivers public events from the Postgres outbox to the
// operator's destinations over Web Push (ADR-013, ADR-015).
package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/config"
	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/notifier"
	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/push"
	"github.com/mwelch21/OddsExecutionEngine/services/notifier/internal/store"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	if err := run(log); err != nil {
		log.Error("notifier.exited", "error", err)
		os.Exit(1)
	}
}

func run(log *slog.Logger) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	pool, err := pgxpool.New(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	defer pool.Close()

	n := &notifier.Notifier{
		Store:     store.New(pool),
		Sender:    push.NewWebPushSender(cfg.VAPIDPublicKey, cfg.VAPIDPrivateKey, cfg.VAPIDSubject),
		Log:       log,
		BatchSize: cfg.BatchSize,
		Lease:     cfg.ClaimLease,
		Now:       time.Now,
		AppOrigin: cfg.AppOrigin,
	}

	// Reconnect the listener with backoff: Postgres restarts and a stack that
	// starts the notifier before migrations ran must not kill the process.
	backoff := time.Second
	for {
		listener, err := store.Listen(ctx, cfg.DatabaseURL, notifier.Channel)
		if err == nil {
			log.Info("notifier.listening", "channel", notifier.Channel)
			backoff = time.Second
			err = n.Run(ctx, listener, cfg.SweepInterval)
			listener.Close(context.Background()) //nolint:errcheck // shutting down
		}
		if ctx.Err() != nil {
			log.Info("notifier.stopped")
			return nil
		}
		log.Error("notifier.restarting", "error", err, "in", backoff.String())
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(backoff):
		}
		backoff = min(backoff*2, 30*time.Second)
	}
}
