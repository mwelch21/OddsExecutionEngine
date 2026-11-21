package config

import "testing"

func setRequired(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://localhost/db")
	t.Setenv("VAPID_PUBLIC_KEY", "pub")
	t.Setenv("VAPID_PRIVATE_KEY", "priv")
	t.Setenv("VAPID_SUBJECT", "mailto:ops@example.com")
}

func TestAppOriginIsRequiredAndNormalised(t *testing.T) {
	setRequired(t)
	t.Setenv("APP_ORIGIN", "")
	if _, err := Load(); err == nil {
		t.Fatal("missing APP_ORIGIN must fail at start")
	}

	t.Setenv("APP_ORIGIN", "https://phone.tailnet.ts.net/")
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.AppOrigin != "https://phone.tailnet.ts.net" {
		t.Fatalf("AppOrigin = %q", cfg.AppOrigin)
	}
}

func TestAppOriginMustBeAnAbsoluteOrigin(t *testing.T) {
	setRequired(t)
	for _, bad := range []string{"phone.tailnet.ts.net", "/app", "https://host/app", "ftp://host"} {
		t.Setenv("APP_ORIGIN", bad)
		if _, err := Load(); err == nil {
			t.Fatalf("APP_ORIGIN %q was accepted", bad)
		}
	}
}
