// SPDX-License-Identifier: Apache-2.0

package startcheck

import (
	"context"
	"errors"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

func env(values map[string]string) func(string) string {
	return func(name string) string { return values[name] }
}

func readable(t *testing.T) string {
	path := filepath.Join(t.TempDir(), "dsn")
	if err := os.WriteFile(path, []byte("postgres://check@db/dewpoint?sslmode=disable\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestTheModeIsRequiredAndNeverOffByOmission(t *testing.T) {
	for _, mode := range []string{"", "maybe", "ON", "true"} {
		if _, err := FromEnv(env(map[string]string{EnvMode: mode}), os.ReadFile); err == nil {
			t.Fatalf("mode %q accepted", mode)
		}
	}
	s, err := FromEnv(env(map[string]string{EnvMode: ModeOff}), os.ReadFile)
	if err != nil || s.Mode != ModeOff {
		t.Fatalf("off: %v %+v", err, s)
	}
}

func TestOnNeedsAReadableDSNADeadlineAndTheQueue(t *testing.T) {
	dsn := readable(t)
	whole := map[string]string{EnvMode: ModeOn, EnvDSNFile: dsn, EnvDeadline: "2s", EnvQueue: "dewpoint-engine"}
	s, err := FromEnv(env(whole), os.ReadFile)
	if err != nil || s.Mode != ModeOn || s.DSN != "postgres://check@db/dewpoint?sslmode=disable" ||
		s.Deadline != 2*time.Second || s.Queue != "dewpoint-engine" {
		t.Fatalf("on: %v %+v", err, s)
	}
	for name, change := range map[string]map[string]string{
		"no DSN file":         {EnvDSNFile: ""},
		"an unreadable one":   {EnvDSNFile: filepath.Join(t.TempDir(), "absent")},
		"no deadline":         {EnvDeadline: ""},
		"a deadline of zero":  {EnvDeadline: "0s"},
		"a deadline unparsed": {EnvDeadline: "soon"},
		"no queue":            {EnvQueue: ""},
	} {
		values := map[string]string{}
		for k, v := range whole {
			values[k] = v
		}
		for k, v := range change {
			values[k] = v
		}
		if _, err := FromEnv(env(values), os.ReadFile); err == nil {
			t.Fatalf("%s: accepted", name)
		}
	}
	empty := filepath.Join(t.TempDir(), "empty")
	if err := os.WriteFile(empty, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	whole[EnvDSNFile] = empty
	if _, err := FromEnv(env(whole), os.ReadFile); err == nil {
		t.Fatal("an empty DSN file accepted")
	}
}

func TestReportedNamesTheModeAsConfigured(t *testing.T) {
	for value, want := range map[string]string{"on": "on", "off": "off", "": "unset", "maybe": "invalid"} {
		if got := Reported(env(map[string]string{EnvMode: value})); got != want {
			t.Fatalf("%q reported %q", value, got)
		}
	}
}

type row struct {
	value bool
	err   error
}

func (r row) Scan(dest ...any) error {
	if r.err != nil {
		return r.err
	}
	*dest[0].(*bool) = r.value
	return nil
}

type querier struct {
	row  row
	sql  string
	args []any
}

func (q *querier) QueryRow(_ context.Context, sql string, args ...any) pgx.Row {
	q.sql, q.args = sql, args
	return q.row
}

func TestTheDatabasesAnswerIsTheVerdictAndAnyErrorIsUnavailable(t *testing.T) {
	for _, c := range []struct {
		row  row
		want Verdict
	}{
		{row{value: true}, Allow},
		{row{value: false}, NotPermitted},
		{row{err: errors.New("anything")}, Unavailable},
		{row{err: context.DeadlineExceeded}, Unavailable},
	} {
		q := &querier{row: c.row}
		got := DB{Pool: q, Deadline: time.Second}.Check(context.Background(), "t:a:run:b", "c")
		if got != c.want || q.sql != Query || len(q.args) != 2 || q.args[0] != "t:a:run:b" || q.args[1] != "c" {
			t.Fatalf("%+v: %v (%q %v)", c.row, got, q.sql, q.args)
		}
	}
}

// A server that accepts and never answers: the check's one deadline covers the connect and its handshake.
func TestAConnectionThatNeverAnswersIsUnavailableWithinTheDeadline(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			defer conn.Close()
		}
	}()
	deadline := 300 * time.Millisecond
	pool, err := NewPool(context.Background(), Settings{
		Mode: ModeOn, DSN: "postgres://check:pw@" + listener.Addr().String() + "/dewpoint?sslmode=disable",
		Deadline: deadline, Queue: "dewpoint-engine",
	})
	if err != nil {
		t.Fatalf("a pool that can't connect yet is still made (it connects lazily): %v", err)
	}
	defer pool.Close()
	began := time.Now()
	got := DB{Pool: pool, Deadline: deadline}.Check(context.Background(), "t:a:run:b", "c")
	if took := time.Since(began); got != Unavailable || took > deadline+time.Second {
		t.Fatalf("%v after %v", got, took)
	}
}
