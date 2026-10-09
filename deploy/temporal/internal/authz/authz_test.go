// SPDX-License-Identifier: Apache-2.0

package authz

import (
	"context"
	"crypto/x509/pkix"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	enumspb "go.temporal.io/api/enums/v1"
	namespacepb "go.temporal.io/api/namespace/v1"
	"go.temporal.io/api/workflowservice/v1"
	"go.temporal.io/server/common/authorization"
	"go.temporal.io/server/common/log"
	"google.golang.org/protobuf/types/known/durationpb"

	"dewpoint.local/temporal-server/internal/audit"
	"dewpoint.local/temporal-server/internal/policy"
)

const day = 24 * time.Hour

type trail struct {
	records []audit.Record
	broken  bool
}

func (t *trail) Write(_ context.Context, r audit.Record) error {
	if t.broken {
		return errors.New("refused")
	}
	t.records = append(t.records, r)
	return nil
}

type namespaces map[string]policy.Config

func (n namespaces) Config(_ context.Context, name string) (policy.Config, error) {
	c, ok := n[name]
	if !ok {
		return policy.Config{}, errors.New("not found")
	}
	return c, nil
}

func authorizer(t *trail, current namespaces) *Authorizer {
	return &Authorizer{
		Delegate: authorization.NewDefaultAuthorizer(), Namespaces: current, Audit: t,
		NewNamespace: policy.Config{History: policy.ArchivalDisabled, Visibility: policy.ArchivalDisabled},
		Server:       "sha256:test", Logger: log.NewNoopLogger(),
	}
}

var admin = &authorization.Claims{Subject: "proof-admin", AuthType: "jwt", System: authorization.RoleAdmin}

func register(retention time.Duration) *authorization.CallTarget {
	return &authorization.CallTarget{APIName: policy.RegisterNamespace, Namespace: "proof-ns",
		Request: &workflowservice.RegisterNamespaceRequest{Namespace: "proof-ns",
			WorkflowExecutionRetentionPeriod: durationpb.New(retention)}}
}

func update(config *namespacepb.NamespaceConfig) *authorization.CallTarget {
	return &authorization.CallTarget{APIName: policy.UpdateNamespace, Namespace: "proof-ns",
		Request: &workflowservice.UpdateNamespaceRequest{Namespace: "proof-ns", Config: config}}
}

func decide(t *testing.T, a *Authorizer, claims *authorization.Claims, target *authorization.CallTarget) bool {
	t.Helper()
	result, err := a.Authorize(context.Background(), claims, target)
	if err != nil {
		t.Fatal(err)
	}
	return result.Decision == authorization.DecisionAllow
}

func TestThirtyDaysAllowedThirtyOneRefusedEachAudited(t *testing.T) {
	audited := &trail{}
	a := authorizer(audited, nil)
	if !decide(t, a, admin, register(30*day)) || decide(t, a, admin, register(31*day)) {
		t.Fatal("30 days must be allowed and 31 refused")
	}
	if len(audited.records) != 2 || !audited.records[0].Allowed || audited.records[1].Allowed {
		t.Fatalf("audited %+v", audited.records)
	}
	r := audited.records[1]
	if r.Subject != "proof-admin" || r.Namespace != "proof-ns" || r.Server != "sha256:test" ||
		*r.Requested.RetentionSeconds != int64(31*day/time.Second) {
		t.Fatalf("record %+v", r)
	}
}

func TestARefusalNamesItsReason(t *testing.T) {
	result, err := authorizer(&trail{}, nil).Authorize(context.Background(), admin, register(31*day))
	if err != nil || result.Decision != authorization.DecisionDeny || result.Reason == "" {
		t.Fatalf("got %+v, %v", result, err)
	}
}

func TestAnUpdateIsCheckedAgainstTheStoredConfiguration(t *testing.T) {
	stored := namespaces{"proof-ns": {Retention: policy.Retention{Set: true, Seconds: int64(31 * day / time.Second)},
		History: policy.ArchivalDisabled}}
	a := authorizer(&trail{}, stored)
	if decide(t, a, admin, update(nil)) {
		t.Fatal("an update leaving a 31-day retention in place was allowed")
	}
	if !decide(t, a, admin, update(&namespacepb.NamespaceConfig{WorkflowExecutionRetentionTtl: durationpb.New(7 * day)})) {
		t.Fatal("an update bringing retention back within 30 days was refused")
	}
	archived := namespaces{"proof-ns": {Retention: policy.Retention{Set: true, Seconds: 86400},
		History: policy.ArchivalEnabled}}
	if decide(t, authorizer(&trail{}, archived), admin, update(nil)) {
		t.Fatal("an update leaving archival enabled was allowed")
	}
}

func TestEnablingArchivalIsRefused(t *testing.T) {
	stored := namespaces{"proof-ns": {Retention: policy.Retention{Set: true, Seconds: 86400}}}
	enable := update(&namespacepb.NamespaceConfig{VisibilityArchivalState: enumspb.ARCHIVAL_STATE_ENABLED})
	if decide(t, authorizer(&trail{}, stored), admin, enable) {
		t.Fatal("enabling visibility archival was allowed")
	}
	unknown := update(&namespacepb.NamespaceConfig{HistoryArchivalState: enumspb.ArchivalState(99)})
	if decide(t, authorizer(&trail{}, stored), admin, unknown) {
		t.Fatal("an archival state this build doesn't know was allowed")
	}
}

func TestAnUnwritableTrailRefusesThirtyDays(t *testing.T) {
	if decide(t, authorizer(&trail{broken: true}, nil), admin, register(30*day)) {
		t.Fatal("allowed without its audit record")
	}
}

func TestAnInspectedCallWithAnotherRequestTypeIsRefused(t *testing.T) {
	stored := namespaces{"proof-ns": {Retention: policy.Retention{Set: true, Seconds: 86400}}}
	odd := &authorization.CallTarget{APIName: policy.UpdateNamespace, Namespace: "proof-ns",
		Request: &workflowservice.DescribeNamespaceRequest{Namespace: "proof-ns"}}
	if decide(t, authorizer(&trail{}, stored), admin, odd) {
		t.Fatal("an UpdateNamespace whose request couldn't be read was allowed")
	}
}

func TestTheRoleStillDecidesWithinTheRules(t *testing.T) {
	writer := &authorization.Claims{Subject: "dewpoint", AuthType: "jwt",
		Namespaces: map[string]authorization.Role{"proof-ns": authorization.RoleWriter}}
	audited := &trail{}
	if decide(t, authorizer(audited, nil), writer, register(7*day)) {
		t.Fatal("a namespace writer registered a namespace")
	}
	if len(audited.records) != 1 || audited.records[0].Allowed {
		t.Fatalf("audited %+v", audited.records)
	}
}

func TestOtherCallsAreTheRoleAloneAndUnaudited(t *testing.T) {
	audited := &trail{}
	start := &authorization.CallTarget{APIName: "/temporal.api.workflowservice.v1.WorkflowService/StartWorkflowExecution",
		Namespace: "proof-ns", Request: &workflowservice.StartWorkflowExecutionRequest{Namespace: "proof-ns"}}
	if !decide(t, authorizer(audited, nil), admin, start) || decide(t, authorizer(audited, nil), nil, start) {
		t.Fatal("the role must decide a start")
	}
	if len(audited.records) != 0 {
		t.Fatalf("audited %+v", audited.records)
	}
}

// D12.1 against this binary: every RPC of the services the frontend registers, as compiled in, is classed, and the
// table names nothing else but the Nexus routes' API names.
func TestEveryFrontendRPCIsClassedAndTheTableNamesNoOther(t *testing.T) {
	served := map[string]bool{}
	for _, rpc := range RPCs() {
		served[rpc.API] = true
		if rpc.Class == policy.Unclassed.String() {
			t.Errorf("unclassed: %s", rpc.API)
		}
	}
	for api := range policy.Table() {
		if !served[api] {
			t.Errorf("classed but not served: %s", api)
		}
	}
}

func TestCertificateRoles(t *testing.T) {
	path := filepath.Join(t.TempDir(), "roles.json")
	// the cluster's scope is Temporal's own, temporal-system, as its JWT claim mapper reads it (R3-B's lesson)
	if err := os.WriteFile(path, []byte(`{"proof-admin": ["temporal-system:admin"], "dewpoint": ["proof-ns:write"]}`), 0o600); err != nil {
		t.Fatal(err)
	}
	m, err := LoadCertClaims(path)
	if err != nil {
		t.Fatal(err)
	}
	got, _ := m.GetClaims(&authorization.AuthInfo{TLSSubject: &pkix.Name{CommonName: "proof-admin"}})
	if got.System != authorization.RoleAdmin {
		t.Fatalf("admin: %+v", got)
	}
	got, _ = m.GetClaims(&authorization.AuthInfo{TLSSubject: &pkix.Name{CommonName: "dewpoint"}})
	if got.System != 0 || got.Namespaces["proof-ns"] != authorization.RoleWriter {
		t.Fatalf("dewpoint: %+v", got)
	}
	got, _ = m.GetClaims(&authorization.AuthInfo{TLSSubject: &pkix.Name{CommonName: "someone-else"}})
	if got.System != 0 || len(got.Namespaces) != 0 {
		t.Fatalf("an unlisted certificate has a role: %+v", got)
	}
	got, _ = m.GetClaims(&authorization.AuthInfo{AuthToken: "Bearer x"}) // no certificate: mTLS only
	if got.Subject != "" || got.System != 0 {
		t.Fatalf("no certificate: %+v", got)
	}
	if err := os.WriteFile(path, []byte(`{"x": ["temporal-system:owner"]}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadCertClaims(path); err == nil {
		t.Fatal("an unknown role was accepted")
	}
	// "system" would be a namespace of that name to Temporal's JWT mapper, never the cluster: refused, not guessed
	if err := os.WriteFile(path, []byte(`{"x": ["system:admin"]}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadCertClaims(path); err == nil || !strings.Contains(err.Error(), "temporal-system") {
		t.Fatalf("an ambiguous system scope: %v", err)
	}
}
