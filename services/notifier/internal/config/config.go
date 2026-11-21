// Package config reads the notifier's settings from the environment.
package config

import (
	"errors"
	"fmt"
	"net/url"
	"os"
	"strings"
	"time"
)

// Config holds everything the notifier needs. It is the only process that
// receives the VAPID private key (ADR-013, #59).
type Config struct {
	DatabaseURL     string
	VAPIDPublicKey  string
	VAPIDPrivateKey string
	VAPIDSubject    string
	AppOrigin       string
	SweepInterval   time.Duration
	ClaimLease      time.Duration
	BatchSize       int
}

// Load reads the environment. Missing required values are an error, so a
// misconfigured notifier fails at start rather than on the first push.
func Load() (Config, error) {
	cfg := Config{
		DatabaseURL:     os.Getenv("DATABASE_URL"),
		VAPIDPublicKey:  os.Getenv("VAPID_PUBLIC_KEY"),
		VAPIDPrivateKey: os.Getenv("VAPID_PRIVATE_KEY"),
		VAPIDSubject:    os.Getenv("VAPID_SUBJECT"),
		AppOrigin:       strings.TrimRight(os.Getenv("APP_ORIGIN"), "/"),
		SweepInterval:   30 * time.Second,
		ClaimLease:      60 * time.Second,
		BatchSize:       20,
	}

	var missing []error
	for name, value := range map[string]string{
		"DATABASE_URL":      cfg.DatabaseURL,
		"VAPID_PUBLIC_KEY":  cfg.VAPIDPublicKey,
		"VAPID_PRIVATE_KEY": cfg.VAPIDPrivateKey,
		"VAPID_SUBJECT":     cfg.VAPIDSubject,
		"APP_ORIGIN":        cfg.AppOrigin,
	} {
		if value == "" {
			missing = append(missing, fmt.Errorf("%s is not set", name))
		}
	}
	if len(missing) > 0 {
		return Config{}, errors.Join(missing...)
	}
	// Notification links are built under this origin, and Declarative Web Push
	// needs them absolute: a bare host or a path would ship broken taps.
	if origin, err := url.Parse(cfg.AppOrigin); err != nil ||
		(origin.Scheme != "https" && origin.Scheme != "http") || origin.Host == "" ||
		origin.Path != "" || origin.RawQuery != "" {
		return Config{}, fmt.Errorf("APP_ORIGIN must be an origin such as https://phone.tailnet.ts.net, got %q", cfg.AppOrigin)
	}
	return cfg, nil
}
