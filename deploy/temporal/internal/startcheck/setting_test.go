// SPDX-License-Identifier: Apache-2.0

package startcheck

import (
	"runtime"
	"testing"
)

// ending is a test that records how a helper ended it: failed, skipped, or not at all.
type ending struct {
	testing.TB
	how string
}

func (e *ending) Helper() {}

func (e *ending) Fatalf(string, ...any) {
	e.how = "failed"
	runtime.Goexit()
}

func (e *ending) Skipf(string, ...any) {
	e.how = "skipped"
	runtime.Goexit()
}

func ended(f func(testing.TB)) string {
	e := &ending{how: "returned"}
	done := make(chan struct{})
	go func() {
		defer close(done)
		f(e)
	}()
	<-done
	return e.how
}

// The database tests' settings: where the backend's database-test command requires them (DEWPOINT_TEST_PG_REQUIRED),
// a missing one fails the test; elsewhere (`go test ./...` with no database) it's skipped.
func TestAMissingDatabaseSettingFailsWhereItIsRequiredAndIsSkippedElsewhere(t *testing.T) {
	t.Setenv("DEWPOINT_TEST_PG_NOTHING", "")
	for required, want := range map[string]string{"1": "failed", "": "skipped"} {
		t.Setenv(EnvTestRequired, required)
		if got := ended(func(tb testing.TB) { setting(tb, "DEWPOINT_TEST_PG_NOTHING", "nothing") }); got != want {
			t.Fatalf("required %q: %s, want %s", required, got, want)
		}
	}
	t.Setenv("DEWPOINT_TEST_PG_SOMETHING", "x")
	if got := ended(func(tb testing.TB) { setting(tb, "DEWPOINT_TEST_PG_SOMETHING", "something") }); got != "returned" {
		t.Fatalf("a setting that's there: %s", got)
	}
}
