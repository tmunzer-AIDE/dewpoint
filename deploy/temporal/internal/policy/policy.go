// SPDX-License-Identifier: Apache-2.0

// Package policy decides D12's namespace rules (2b-4b M4), on Go's standard library alone so it's tested without
// building the server: a namespace's effective retention at most 30 days and its archival disabled after any
// RegisterNamespace or UpdateNamespace; every other API that can change a namespace's configuration refused; every
// namespace-changing decision, allowed or refused, written to the audit trail before it's returned, and refused when
// that write fails. Everything else is the caller's role alone (Temporal's default authorizer). internal/authz adapts
// the server's types to these.
package policy

import "fmt"

// MaxRetentionSeconds is D3g's cap: 30 days.
const MaxRetentionSeconds = 30 * 24 * 60 * 60

// Retention is a protobuf duration as requested or stored; Set is false when a request leaves it out.
type Retention struct {
	Set     bool
	Seconds int64
	Nanos   int32
}

type Archival int

const (
	ArchivalUnspecified Archival = iota // left out of a request: the current state stays
	ArchivalDisabled
	ArchivalEnabled
)

// Config is a namespace's retention and archival states: as requested, as they are now, or as they'd be.
type Config struct {
	Retention  Retention
	History    Archival
	Visibility Archival
}

// Effective is the configuration after a request: each setting it names, else the current one.
func Effective(current, requested Config) Config {
	effective := current
	if requested.Retention.Set {
		effective.Retention = requested.Retention
	}
	if requested.History != ArchivalUnspecified {
		effective.History = requested.History
	}
	if requested.Visibility != ArchivalUnspecified {
		effective.Visibility = requested.Visibility
	}
	return effective
}

// Violation says how a configuration breaks the rules; "" when it doesn't.
func Violation(c Config) string {
	r := c.Retention
	switch {
	case !r.Set:
		return "no retention: one of at most 30 days is required"
	case r.Seconds < 0 || r.Nanos < 0:
		return "a negative retention"
	case r.Nanos > 999_999_999:
		// a protobuf duration's nanos stay within a second; Temporal stores them unchecked and reads more as seconds
		return "a malformed retention (nanos beyond a second)"
	case r.Seconds > MaxRetentionSeconds || (r.Seconds == MaxRetentionSeconds && r.Nanos > 0):
		return fmt.Sprintf("a retention above 30 days (%d s)", r.Seconds)
	case c.History == ArchivalEnabled:
		return "history archival enabled: archival must stay disabled"
	case c.Visibility == ArchivalEnabled:
		return "visibility archival enabled: archival must stay disabled"
	}
	return ""
}

// Decision is what the audit trail records and the authorizer returns.
type Decision struct {
	Allowed   bool
	Reason    string
	Effective *Config // for RegisterNamespace and UpdateNamespace, once the current configuration was read
}

// Steps are the decision's effects, each the adapter's: the configuration now (for RegisterNamespace, the cluster's
// defaults for a new namespace, retention unset; for UpdateNamespace, the namespace's, read from persistence), the
// caller's role (Temporal's default authorizer), and the audit record's write.
type Steps struct {
	Current  func() (Config, error)
	Delegate func() bool
	Audit    func(Decision) error
}

// Decide decides one call. `requested` is the request's configuration (RegisterNamespace and UpdateNamespace only);
// nil when the adapter couldn't read the request, which refuses an inspected call.
func Decide(api string, requested *Config, steps Steps) Decision {
	var d Decision
	switch Classify(api) {
	case Delegated:
		return Decision{Allowed: steps.Delegate(), Reason: "the caller's role"}
	case Closed:
		return Decision{Reason: "Nexus isn't open on this server"}
	case Unclassed:
		d = Decision{Reason: "an API the authorizer's table doesn't class"}
	case Refused:
		d = Decision{Reason: "an API that can change a namespace's configuration, never allowed"}
	case Inspected:
		d = inspect(requested, steps)
	}
	if err := steps.Audit(d); err != nil {
		return Decision{Reason: "the audit record couldn't be written", Effective: d.Effective}
	}
	return d
}

func inspect(requested *Config, steps Steps) Decision {
	if requested == nil {
		return Decision{Reason: "the request couldn't be read"}
	}
	current, err := steps.Current()
	if err != nil {
		return Decision{Reason: "the namespace's configuration couldn't be read"}
	}
	effective := Effective(current, *requested)
	if v := Violation(effective); v != "" {
		return Decision{Reason: v, Effective: &effective}
	}
	if !steps.Delegate() {
		return Decision{Reason: "the caller's role doesn't allow it", Effective: &effective}
	}
	return Decision{Allowed: true, Reason: "within the namespace rules", Effective: &effective}
}
