// SPDX-License-Identifier: Apache-2.0

package startcheck

import (
	"context"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

// Against a database migrated to 0052 (DEWPOINT_TEST_PG_DSN, its owner; DEWPOINT_TEST_PG_CHECK_DSN, a LOGIN member of
// dewpoint_start_check; DEWPOINT_TEST_PG_ALLOW, an eligible request in it): what the check answers, and what its one
// deadline does when the database is there but can't answer in time, or won't let it in. The backend's database-test
// command (backend/tests/core/test_start_check_go.py) provides them all and requires them (EnvTestRequired): there,
// a missing one fails; under a plain `go test ./...`, with no database, these tests are skipped.

// EnvTestRequired makes every database setting required: a test missing one fails rather than skips.
const EnvTestRequired = "DEWPOINT_TEST_PG_REQUIRED"

func setting(t testing.TB, name, what string) string {
	t.Helper()
	value := os.Getenv(name)
	if value == "" {
		if os.Getenv(EnvTestRequired) != "" {
			t.Fatalf("%s (%s) is required here, and missing: the database tests' setup didn't run", name, what)
		}
		t.Skipf("%s names %s", name, what)
	}
	return value
}

func databases(t *testing.T) (string, string) {
	t.Helper()
	return setting(t, "DEWPOINT_TEST_PG_DSN", "a database migrated to 0052, as its owner"),
		setting(t, "DEWPOINT_TEST_PG_CHECK_DSN", "a LOGIN member of dewpoint_start_check")
}

const deadline = 500 * time.Millisecond

func checkWith(t *testing.T, dsn string) (DB, func()) {
	pool, err := NewPool(context.Background(), Settings{Mode: ModeOn, DSN: dsn, Deadline: deadline, Queue: "q"})
	if err != nil {
		t.Fatal(err)
	}
	return DB{Pool: pool, Deadline: deadline}, pool.Close
}

func within(t *testing.T, check DB, want Verdict) {
	t.Helper()
	began := time.Now()
	got := check.Check(context.Background(), "t:00000000-0000-0000-0000-000000000001:run:00000000-0000-0000-0000-000000000002",
		"00000000-0000-0000-0000-000000000003")
	if took := time.Since(began); got != want || took > deadline+time.Second {
		t.Fatalf("%v after %v, want %v", got, took, want)
	}
}

// An eligible request (DEWPOINT_TEST_PG_ALLOW: its workflow id and its recorded start request id, set up by the
// backend's database-test command with the function tests' own `starting`: admitted, then `starting` with one send
// counted, its id recorded and its root evidence written) is allowed; the same workflow id with another start
// request id isn't.
func TestDatabaseAnEligibleRequestIsAllowedAndOnlyByItsOwnStartRequestID(t *testing.T) {
	_, dsn := databases(t)
	ids := strings.Fields(setting(t, "DEWPOINT_TEST_PG_ALLOW", "an eligible request: its workflow id and start request id"))
	if len(ids) != 2 {
		t.Fatalf("DEWPOINT_TEST_PG_ALLOW names a workflow id and a start request id, got %d fields", len(ids))
	}
	check, done := checkWith(t, dsn)
	defer done()
	if got := check.Check(context.Background(), ids[0], ids[1]); got != Allow {
		t.Fatalf("the eligible request: %v, want %v", got, Allow)
	}
	if got := check.Check(context.Background(), ids[0], "00000000-0000-4000-8000-000000000000"); got != NotPermitted {
		t.Fatalf("another start request id: %v, want %v", got, NotPermitted)
	}
}

func TestDatabaseNoEligibleRequestIsNotPermitted(t *testing.T) {
	_, dsn := databases(t)
	check, done := checkWith(t, dsn)
	defer done()
	within(t, check, NotPermitted)
}

func TestDatabaseARefusedLoginIsUnavailable(t *testing.T) {
	_, dsn := databases(t)
	wrong, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	wrong.User = url.UserPassword(wrong.User.Username(), "not-the-password")
	check, done := checkWith(t, wrong.String())
	defer done()
	within(t, check, Unavailable)
}

func TestDatabaseABusyPoolIsUnavailableWithinTheDeadline(t *testing.T) {
	_, dsn := databases(t)
	one, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	query := one.Query()
	query.Set("pool_max_conns", "1")
	one.RawQuery = query.Encode()
	pool, err := NewPool(context.Background(), Settings{Mode: ModeOn, DSN: one.String(), Deadline: deadline, Queue: "q"})
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	held, err := pool.Acquire(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer held.Release()
	within(t, DB{Pool: pool, Deadline: deadline}, Unavailable)
}

func TestDatabaseALockTheCheckWaitsOnIsUnavailableNotNotPermitted(t *testing.T) {
	owner, dsn := databases(t)
	ctx := context.Background()
	locker, err := pgx.Connect(ctx, owner)
	if err != nil {
		t.Fatal(err)
	}
	defer locker.Close(ctx)
	tx, err := locker.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(ctx) //nolint:errcheck // the lock's end
	if _, err := tx.Exec(ctx, "LOCK TABLE run_requests IN ACCESS EXCLUSIVE MODE"); err != nil {
		t.Fatal(err)
	}
	check, done := checkWith(t, dsn)
	defer done()
	within(t, check, Unavailable)
}

// The start-check proof's outage, at this level (its cases A and C, and its teardown's reconnect): the login made
// NOLOGIN and its sessions ended denies Unavailable, and once LOGIN is restored the same pool connects again.
func TestDatabaseALoginRefusedOnceItsSessionsEndIsUnavailableThenTheSamePoolReconnects(t *testing.T) {
	owner, dsn := databases(t)
	ctx := context.Background()
	admin, err := pgx.Connect(ctx, owner)
	if err != nil {
		t.Fatal(err)
	}
	defer admin.Close(ctx)
	parsed, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	name := parsed.User.Username()
	role := pgx.Identifier{name}.Sanitize()
	check, done := checkWith(t, dsn)
	defer done()
	within(t, check, NotPermitted) // its pool now holds a session
	if _, err := admin.Exec(ctx, "ALTER ROLE "+role+" NOLOGIN"); err != nil {
		t.Fatal(err)
	}
	defer admin.Exec(ctx, "ALTER ROLE "+role+" LOGIN") //nolint:errcheck // restored whatever happened
	for until := time.Now().Add(10 * time.Second); ; {
		var left int
		if err := admin.QueryRow(ctx, "SELECT count(*) FROM pg_stat_activity WHERE usename = $1", name).Scan(&left); err != nil {
			t.Fatal(err)
		}
		if left == 0 {
			break
		}
		if time.Now().After(until) {
			t.Fatalf("%d sessions of the login left", left)
		}
		if _, err := admin.Exec(ctx, "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = $1", name); err != nil {
			t.Fatal(err)
		}
		time.Sleep(100 * time.Millisecond)
	}
	within(t, check, Unavailable)
	if _, err := admin.Exec(ctx, "ALTER ROLE "+role+" LOGIN"); err != nil {
		t.Fatal(err)
	}
	within(t, check, NotPermitted)
}
