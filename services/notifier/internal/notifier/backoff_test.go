package notifier

import (
	"testing"
	"time"
)

func TestBackoffDoublesPerAttemptUpToTheCapWithJitter(t *testing.T) {
	for _, tc := range []struct {
		attempts int
		min, max time.Duration
	}{
		{1, 5 * time.Second, 10 * time.Second},
		{2, 10 * time.Second, 20 * time.Second},
		{3, 20 * time.Second, 40 * time.Second},
		{7, 320 * time.Second, 640 * time.Second},
		{8, 7*time.Minute + 30*time.Second, 15 * time.Minute}, // 1280s step is capped
		{1000, 7*time.Minute + 30*time.Second, 15 * time.Minute},
	} {
		low, high := backoff(tc.attempts, 0), backoff(tc.attempts, 0.999999)
		if low != tc.min || high > tc.max || high <= low {
			t.Errorf("backoff(%d) spans [%s, %s], want [%s, %s)", tc.attempts, low, high, tc.min, tc.max)
		}
	}
}
