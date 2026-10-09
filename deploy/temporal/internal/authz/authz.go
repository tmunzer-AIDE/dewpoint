// SPDX-License-Identifier: Apache-2.0

// Package authz is D12's authorizer (2b-4b M4): Temporal's types adapted to internal/policy's decision. It reads a
// namespace's effective configuration from persistence, writes every namespace-changing decision to the audit trail
// before returning it, and leaves the caller's role to Temporal's default authorizer. The same authorizer runs on the
// frontend and the internal frontend (Temporal v1.32.0 gives both the configured authorizer; only the claim mapper
// differs), so the namespace rules hold for the server's own system workers too.
package authz

import (
	"context"
	"fmt"
	"time"

	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/api/workflowservice/v1"
	"go.temporal.io/server/common/authorization"
	"go.temporal.io/server/common/log"
	"go.temporal.io/server/common/log/tag"
	"google.golang.org/protobuf/types/known/durationpb"

	"dewpoint.local/temporal-server/internal/audit"
	"dewpoint.local/temporal-server/internal/policy"
)

// AuditTimeout bounds one audit write: a bucket that doesn't answer refuses the change rather than holding the call.
const AuditTimeout = 5 * time.Second

// Namespaces reads a namespace's configuration now.
type Namespaces interface {
	Config(ctx context.Context, name string) (policy.Config, error)
}

type Authorizer struct {
	Delegate     authorization.Authorizer // Temporal's default authorizer: the caller's role
	Namespaces   Namespaces
	Audit        audit.Writer
	NewNamespace policy.Config // a new namespace's configuration before its request: the cluster's archival defaults
	Server       string        // the server binary's SHA-256, in each record
	Logger       log.Logger
	Now          func() time.Time
}

var _ authorization.Authorizer = (*Authorizer)(nil)

func (a *Authorizer) Authorize(ctx context.Context, claims *authorization.Claims,
	target *authorization.CallTarget) (authorization.Result, error) {
	requested := Requested(target.Request)
	var delegated authorization.Result
	steps := policy.Steps{
		Current: func() (policy.Config, error) {
			if target.APIName == policy.RegisterNamespace {
				return a.NewNamespace, nil
			}
			return a.Namespaces.Config(ctx, target.Namespace)
		},
		Delegate: func() bool {
			result, err := a.Delegate.Authorize(ctx, claims, target)
			delegated = result
			return err == nil && result.Decision == authorization.DecisionAllow
		},
		Audit: func(d policy.Decision) error { return a.write(ctx, claims, target, requested, d) },
	}
	d := policy.Decide(target.APIName, requested, steps)
	switch {
	case d.Allowed:
		return delegated, nil
	case policy.Classify(target.APIName) == policy.Delegated:
		return authorization.Result{Decision: authorization.DecisionDeny, Reason: delegated.Reason}, nil
	}
	return authorization.Result{Decision: authorization.DecisionDeny, Reason: d.Reason}, nil
}

func (a *Authorizer) write(ctx context.Context, claims *authorization.Claims, target *authorization.CallTarget,
	requested *policy.Config, d policy.Decision) error {
	now := time.Now
	if a.Now != nil {
		now = a.Now
	}
	r := audit.NewRecord(now())
	r.Server, r.API, r.Namespace, r.Allowed, r.Reason = a.Server, target.APIName, target.Namespace, d.Allowed, d.Reason
	if claims != nil {
		r.Subject, r.AuthType = claims.Subject, claims.AuthType
	}
	r.Requested, r.Effective = Settings(requested), Settings(d.Effective)
	ctx, cancel := context.WithTimeout(ctx, AuditTimeout)
	defer cancel()
	err := a.Audit.Write(ctx, r)
	tags := []tag.Tag{tag.NewStringTag("api", r.API), tag.NewStringTag("namespace-name", r.Namespace),
		tag.NewBoolTag("allowed", r.Allowed), tag.NewStringTag("reason", r.Reason),
		tag.NewStringTag("decision-id", r.ID)}
	if err != nil {
		// the error's type only: its message can carry the bucket's answer
		a.Logger.Error("namespace change refused: its audit record couldn't be written",
			append(tags, tag.NewStringTag("error-type", fmt.Sprintf("%T", err)))...)
		return err
	}
	a.Logger.Info("namespace change decided", tags...)
	return nil
}

// Requested is a RegisterNamespace's or UpdateNamespace's configuration; nil for any other request, which refuses
// an inspected call (internal/policy).
func Requested(request any) *policy.Config {
	switch r := request.(type) {
	case *workflowservice.RegisterNamespaceRequest:
		return &policy.Config{Retention: retention(r.GetWorkflowExecutionRetentionPeriod()),
			History: archival(r.GetHistoryArchivalState()), Visibility: archival(r.GetVisibilityArchivalState())}
	case *workflowservice.UpdateNamespaceRequest:
		c := r.GetConfig() // nil-safe: no configuration changes nothing
		return &policy.Config{Retention: retention(c.GetWorkflowExecutionRetentionTtl()),
			History: archival(c.GetHistoryArchivalState()), Visibility: archival(c.GetVisibilityArchivalState())}
	}
	return nil
}

func retention(d *durationpb.Duration) policy.Retention {
	if d == nil {
		return policy.Retention{}
	}
	return policy.Retention{Set: true, Seconds: d.GetSeconds(), Nanos: d.GetNanos()}
}

// archival: a state this build doesn't know counts as enabled (refused).
func archival(state enumspb.ArchivalState) policy.Archival {
	switch state {
	case enumspb.ARCHIVAL_STATE_UNSPECIFIED:
		return policy.ArchivalUnspecified
	case enumspb.ARCHIVAL_STATE_DISABLED:
		return policy.ArchivalDisabled
	}
	return policy.ArchivalEnabled
}

// Settings is a configuration as the audit record carries it.
func Settings(c *policy.Config) *audit.Settings {
	if c == nil {
		return nil
	}
	s := &audit.Settings{HistoryArchival: archivalName(c.History), VisibilityArchival: archivalName(c.Visibility)}
	if c.Retention.Set {
		seconds := c.Retention.Seconds
		s.RetentionSeconds, s.RetentionNanos = &seconds, c.Retention.Nanos
	}
	return s
}

func archivalName(a policy.Archival) string {
	return [...]string{"unspecified", "disabled", "enabled"}[a]
}
