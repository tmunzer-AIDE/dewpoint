// SPDX-License-Identifier: Apache-2.0

package audit

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type kept struct{ records []Record }

func (k *kept) Write(_ context.Context, r Record) error { k.records = append(k.records, r); return nil }

func TestARecordIsKeyedByItsDayAndID(t *testing.T) {
	at := time.Date(2026, 10, 9, 23, 59, 59, 0, time.FixedZone("CEST", 2*3600))
	r := NewRecord(at)
	key := Key("dewpoint/", r)
	if !strings.HasPrefix(key, "dewpoint/temporal-authorizer/2026-10-09/") || !strings.HasSuffix(key, r.ID+".json") {
		t.Fatalf("key %q", key)
	}
	if other := NewRecord(at); other.ID == r.ID {
		t.Fatal("two records share an id")
	}
}

func TestARecordCarriesTheDecisionAndNoCredentials(t *testing.T) {
	r := NewRecord(time.Now())
	r.API, r.Namespace, r.Subject, r.AuthType = "/x/RegisterNamespace", "proof-ns", "dewpoint-proof", "jwt"
	r.Allowed, r.Reason = false, "a retention above 30 days (2678400 s)"
	body, err := json.Marshal(r)
	if err != nil {
		t.Fatal(err)
	}
	var back map[string]any
	if err := json.Unmarshal(body, &back); err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"id", "at", "api", "namespace", "subject", "auth_type", "allowed", "reason"} {
		if _, ok := back[field]; !ok {
			t.Fatalf("no %q in %s", field, body)
		}
	}
	for field := range back {
		if strings.Contains(strings.ToLower(field), "token") {
			t.Fatalf("a credential field %q in %s", field, body)
		}
	}
}

func TestAnInjectedFaultFailsOnlyItsNamespacesWrites(t *testing.T) {
	// D12.4's real-target form: a failure injected through the same write path, scoped to the test namespace,
	// the other namespaces' decisions written meanwhile; removing the file ends the injection
	path := filepath.Join(t.TempDir(), "faults")
	if err := os.WriteFile(path, []byte("proof-ns\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	inner := &kept{}
	w := WithFaults(inner, path)
	failed := NewRecord(time.Now())
	failed.Namespace = "proof-ns"
	if err := w.Write(context.Background(), failed); !errors.Is(err, ErrInjected) {
		t.Fatalf("not injected: %v", err)
	}
	other := NewRecord(time.Now())
	other.Namespace = "dewpoint"
	if err := w.Write(context.Background(), other); err != nil || len(inner.records) != 1 {
		t.Fatalf("another namespace's record: %v, %d written", err, len(inner.records))
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := w.Write(context.Background(), failed); err != nil || len(inner.records) != 2 {
		t.Fatalf("after the injection: %v", err)
	}
}

func TestAFaultFileThatCantBeReadFailsClosed(t *testing.T) {
	dir := t.TempDir() // a directory: present, not readable as a file
	w := WithFaults(&kept{}, dir)
	r := NewRecord(time.Now())
	r.Namespace = "dewpoint"
	if err := w.Write(context.Background(), r); err == nil {
		t.Fatal("written although the fault file couldn't be read")
	}
}

func TestNoFaultFileConfiguredWritesThrough(t *testing.T) {
	inner := &kept{}
	if w := WithFaults(inner, ""); w != Writer(inner) {
		t.Fatal("wrapped without a fault file")
	}
}
