// SPDX-License-Identifier: Apache-2.0

// Package startcheck is D12's start check (2b-4b M4, the start-check slice; the upgrade barrier's revisions 16 and
// 17): before a root run starts on the engine queue, the authorizer asks Dewpoint's database whether an eligible
// dispatcher request permits that start (`start_permitted(workflow_id, request_id)`, migration 0052). One deadline
// covers the pool's acquire, the connect and the statement; anything that fails or runs out within it is Unavailable,
// never NotPermitted, so a database that doesn't answer denies with its own fixed reason.
//
// The mode is required (DEWPOINT_AUTHZ_START_CHECK, on or off, no default): nothing is ever off by omission. On needs
// the DSN's file, the deadline and the engine queue's name; off is only ever explicit, and reported as such.
//
// The rollout order: on only after migration 0052 is applied and every dispatcher runs a build with the start call
// (backend/src/dewpoint/apps/dispatcher/start_call.py). An older dispatcher's starts carry no recorded start request
// id, so each is denied, and it reads a denial as a certain refusal: its requests would end dead after ten.
package startcheck

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Verdict is the database's answer for one start.
type Verdict int

const (
	Allow Verdict = iota
	NotPermitted
	Unavailable
)

func (v Verdict) String() string {
	return [...]string{"allow", "not-permitted", "unavailable"}[v]
}

const (
	EnvMode     = "DEWPOINT_AUTHZ_START_CHECK"
	EnvDSNFile  = "DEWPOINT_AUTHZ_START_CHECK_DSN_FILE"
	EnvDeadline = "DEWPOINT_AUTHZ_START_CHECK_DEADLINE"
	EnvQueue    = "DEWPOINT_AUTHZ_START_CHECK_QUEUE"
	ModeOn      = "on"
	ModeOff     = "off"
	// The two fixed denials the dispatcher reads from the error's PermissionDeniedFailure.
	ReasonNotPermitted = "dewpoint:start-not-permitted"
	ReasonUnavailable  = "dewpoint:start-check-unavailable"
	// Query is the check's one statement.
	Query = "SELECT start_permitted($1, $2)"
)

// Settings is the start check's configuration.
type Settings struct {
	Mode     string
	DSN      string
	Deadline time.Duration
	Queue    string
}

// FromEnv reads the settings, refusing any but an explicit mode and, for on, anything missing or unreadable.
func FromEnv(getenv func(string) string, readFile func(string) ([]byte, error)) (Settings, error) {
	s := Settings{Mode: getenv(EnvMode)}
	switch s.Mode {
	case ModeOff:
		return s, nil
	case ModeOn:
	default:
		return s, fmt.Errorf("%s must be %q or %q: the start check is never off by omission", EnvMode, ModeOn, ModeOff)
	}
	path := getenv(EnvDSNFile)
	if path == "" {
		return s, fmt.Errorf("%s is required when the start check is on", EnvDSNFile)
	}
	dsn, err := readFile(path)
	if err != nil {
		return s, fmt.Errorf("%s can't be read: %T", EnvDSNFile, err) // the type only: the path's error can carry it
	}
	s.DSN = strings.TrimSpace(string(dsn))
	if s.DSN == "" {
		return s, fmt.Errorf("%s is empty", EnvDSNFile)
	}
	s.Deadline, err = time.ParseDuration(getenv(EnvDeadline))
	if err != nil || s.Deadline <= 0 {
		return s, fmt.Errorf("%s must be a positive duration", EnvDeadline)
	}
	s.Queue = getenv(EnvQueue)
	if s.Queue == "" {
		return s, fmt.Errorf("%s is required when the start check is on", EnvQueue)
	}
	return s, nil
}

// Reported is the mode as configured, for the inventory: on, off, unset or invalid. It's a prerequisite a proof
// record names, never proof that the admission boundary held.
func Reported(getenv func(string) string) string {
	switch mode := getenv(EnvMode); mode {
	case ModeOn, ModeOff:
		return mode
	case "":
		return "unset"
	}
	return "invalid"
}

// NewPool makes the check's pool. It connects lazily, so a database it can't reach yet isn't a startup failure: each
// check then denies as Unavailable. The connect and the statement are bounded by the deadline as well as by the
// check's context: a lock or a lost server can't hold a connection past it.
func NewPool(ctx context.Context, s Settings) (*pgxpool.Pool, error) {
	config, err := pgxpool.ParseConfig(s.DSN)
	if err != nil {
		return nil, fmt.Errorf("the start check's DSN doesn't parse: %T", err)
	}
	config.ConnConfig.ConnectTimeout = s.Deadline
	ms := strconv.FormatInt(s.Deadline.Milliseconds(), 10)
	config.ConnConfig.RuntimeParams["statement_timeout"] = ms
	config.ConnConfig.RuntimeParams["lock_timeout"] = ms
	config.ConnConfig.RuntimeParams["application_name"] = "dewpoint-start-check"
	return pgxpool.NewWithConfig(ctx, config)
}

// Querier is what the check needs of a pool.
type Querier interface {
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// Checker answers one start.
type Checker interface {
	Check(ctx context.Context, workflowID, requestID string) Verdict
}

// DB is the check against Dewpoint's database.
type DB struct {
	Pool     Querier
	Deadline time.Duration
}

// Check asks once, under one deadline: true is Allow, false NotPermitted, and any error, a timeout included,
// Unavailable. Nothing is cached: each attempt is asked afresh.
func (d DB) Check(ctx context.Context, workflowID, requestID string) Verdict {
	ctx, cancel := context.WithTimeout(ctx, d.Deadline)
	defer cancel()
	var permitted bool
	if err := d.Pool.QueryRow(ctx, Query, workflowID, requestID).Scan(&permitted); err != nil {
		return Unavailable
	}
	if permitted {
		return Allow
	}
	return NotPermitted
}
