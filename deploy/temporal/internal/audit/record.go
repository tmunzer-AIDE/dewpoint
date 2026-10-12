// SPDX-License-Identifier: Apache-2.0

// Package audit is the authorizer's audit trail (D12, 2b-4b M4): one object per namespace-changing decision,
// allowed or refused, in D6's bucket under `temporal-authorizer/<day>/<id>.json`, written once with the authorizer's
// own put-only credentials; the bucket's compliance-mode default retention locks it. A decision is returned only
// after its record is written (internal/policy). This file is the record and the fault injection, on the standard
// library; internal/auditbucket is the writer.
package audit

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"
)

// Record is one decision. It names the caller (a JWT's subject, a certificate's common name, or Temporal's own
// internal principal), never a credential.
type Record struct {
	ID        string    `json:"id"`
	At        time.Time `json:"at"`
	Server    string    `json:"server"` // the server binary's SHA-256
	API       string    `json:"api"`
	Namespace string    `json:"namespace"`
	Subject   string    `json:"subject"`
	AuthType  string    `json:"auth_type"`
	Allowed   bool      `json:"allowed"`
	Reason    string    `json:"reason"`
	Requested *Settings `json:"requested,omitempty"`
	Effective *Settings `json:"effective,omitempty"`
}

// Settings are a namespace's retention and archival states, as requested or as they'd be.
type Settings struct {
	RetentionSeconds   *int64 `json:"retention_seconds,omitempty"` // nil: not set
	RetentionNanos     int32  `json:"retention_nanos,omitempty"`
	HistoryArchival    string `json:"history_archival"`
	VisibilityArchival string `json:"visibility_archival"`
}

// NewRecord starts a record at `at`, with an id that sorts by time and is unique.
func NewRecord(at time.Time) Record {
	random := make([]byte, 8)
	_, _ = rand.Read(random) // never fails (crypto/rand, Go 1.24+)
	at = at.UTC()
	return Record{ID: at.Format("20060102T150405.000000000Z") + "-" + hex.EncodeToString(random), At: at}
}

// Key is a record's object key under `prefix`.
func Key(prefix string, r Record) string {
	return prefix + "temporal-authorizer/" + r.At.UTC().Format("2006-01-02") + "/" + r.ID + ".json"
}

// Writer writes one record, or fails.
type Writer interface {
	Write(ctx context.Context, r Record) error
}

// ErrInjected is the failure an injected fault returns.
var ErrInjected = errors.New("audit write failure injected for this namespace")

// WithFaults injects a write failure for each namespace listed, one per line, in the file at `path`, read on every
// write: real-target qualification's D12.4, scoped to its test namespace, through this same path. No file at the
// path ends the injection; a file that can't be read fails every write (closed). An empty path doesn't wrap.
func WithFaults(w Writer, path string) Writer {
	if path == "" {
		return w
	}
	return faulty{w, path}
}

type faulty struct {
	Writer
	path string
}

func (f faulty) Write(ctx context.Context, r Record) error {
	listed, err := os.ReadFile(f.path)
	switch {
	case errors.Is(err, os.ErrNotExist):
	case err != nil:
		return fmt.Errorf("the fault file couldn't be read: %w", err)
	default:
		for _, namespace := range strings.Fields(string(listed)) {
			if namespace == r.Namespace {
				return ErrInjected
			}
		}
	}
	return f.Writer.Write(ctx, r)
}
