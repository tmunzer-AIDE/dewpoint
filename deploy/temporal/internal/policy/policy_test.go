// SPDX-License-Identifier: Apache-2.0

package policy

import (
	"bufio"
	"errors"
	"os"
	"sort"
	"strings"
	"testing"
)

const day = 24 * 60 * 60

func days(n int64) Retention { return Retention{Set: true, Seconds: n * day} }

// steps: a namespace's configuration now, the caller's role, and an audit trail that records or refuses.
type fake struct {
	current     Config
	unreadable  bool
	role        bool
	auditBroken bool
	asked       int // how often the role was asked
	audited     []Decision
}

func (f *fake) steps() Steps {
	return Steps{
		Current: func() (Config, error) {
			if f.unreadable {
				return Config{}, errors.New("persistence unavailable")
			}
			return f.current, nil
		},
		Delegate: func() bool { f.asked++; return f.role },
		Audit: func(d Decision) error {
			if f.auditBroken {
				return errors.New("bucket refused the write")
			}
			f.audited = append(f.audited, d)
			return nil
		},
	}
}

func TestRegisterWithinTheRulesIsAllowedAndAudited(t *testing.T) {
	f := &fake{role: true}
	d := Decide(RegisterNamespace, &Config{Retention: days(30)}, f.steps())
	if !d.Allowed || len(f.audited) != 1 || !f.audited[0].Allowed {
		t.Fatalf("got %+v, audited %+v", d, f.audited)
	}
}

func TestRetentionAboveThirtyDaysIsRefusedAndAudited(t *testing.T) {
	for name, retention := range map[string]Retention{
		"31 days":            days(31),
		"30 days and 1ns":    {Set: true, Seconds: 30 * day, Nanos: 1},
		"the largest proto":  {Set: true, Seconds: 315_576_000_000},
		"unset, on register": {},
		"negative":           {Set: true, Seconds: -1},
		// the review's C1: Temporal stores nanos it doesn't range-check, and reads 2^31-1 of them as 2.1 s
		"nanos past a second":    {Set: true, Seconds: 30*day - 1, Nanos: 2_147_483_647},
		"a whole second's nanos": {Set: true, Seconds: 30*day - 1, Nanos: 1_000_000_000},
	} {
		t.Run(name, func(t *testing.T) {
			f := &fake{role: true}
			d := Decide(RegisterNamespace, &Config{Retention: retention}, f.steps())
			if d.Allowed || len(f.audited) != 1 || f.audited[0].Allowed || d.Reason == "" {
				t.Fatalf("got %+v, audited %+v", d, f.audited)
			}
		})
	}
}

func TestEnablingArchivalIsRefused(t *testing.T) {
	for name, requested := range map[string]Config{
		"history":    {Retention: days(7), History: ArchivalEnabled},
		"visibility": {Retention: days(7), Visibility: ArchivalEnabled},
	} {
		t.Run(name, func(t *testing.T) {
			f := &fake{role: true}
			if d := Decide(RegisterNamespace, &requested, f.steps()); d.Allowed {
				t.Fatalf("allowed: %+v", d)
			}
		})
	}
}

func TestAnOmittedSettingIsCheckedAgainstTheEffectiveConfiguration(t *testing.T) {
	cases := map[string]struct {
		api       string
		current   Config
		requested Config
		allowed   bool
	}{
		"register: archival omitted, the cluster's default enabled": {
			RegisterNamespace, Config{History: ArchivalEnabled}, Config{Retention: days(7)}, false},
		"update: retention omitted, the namespace at 31 days": {
			UpdateNamespace, Config{Retention: days(31)}, Config{}, false},
		"update: archival omitted, the namespace's history archival enabled": {
			UpdateNamespace, Config{Retention: days(7), History: ArchivalEnabled}, Config{}, false},
		"update: archival omitted, the namespace's visibility archival enabled": {
			UpdateNamespace, Config{Retention: days(7), Visibility: ArchivalEnabled}, Config{}, false},
		"update: a description only, the namespace within the rules": {
			UpdateNamespace, Config{Retention: days(30), History: ArchivalDisabled}, Config{}, true},
		"update: back within the rules from 31 days": {
			UpdateNamespace, Config{Retention: days(31)}, Config{Retention: days(30)}, true},
		"update: archival disabled again": {
			UpdateNamespace, Config{Retention: days(7), History: ArchivalEnabled},
			Config{History: ArchivalDisabled}, true},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			f := &fake{current: c.current, role: true}
			d := Decide(c.api, &c.requested, f.steps())
			if d.Allowed != c.allowed || len(f.audited) != 1 {
				t.Fatalf("got %+v, audited %+v", d, f.audited)
			}
		})
	}
}

func TestAnUnreadableNamespaceRefusesTheChange(t *testing.T) {
	f := &fake{unreadable: true, role: true}
	d := Decide(UpdateNamespace, &Config{Retention: days(7)}, f.steps())
	if d.Allowed || len(f.audited) != 1 || f.asked != 0 {
		t.Fatalf("got %+v, audited %+v, role asked %d", d, f.audited, f.asked)
	}
}

func TestAnUnwritableAuditTrailRefusesEveryChange(t *testing.T) {
	// D12.4: a 30-day change included
	for _, api := range []string{RegisterNamespace, UpdateNamespace} {
		f := &fake{role: true, auditBroken: true, current: Config{Retention: days(7)}}
		if d := Decide(api, &Config{Retention: days(30)}, f.steps()); d.Allowed {
			t.Fatalf("%s allowed without its audit record: %+v", api, d)
		}
	}
}

func TestTheCallersRoleStillDecides(t *testing.T) {
	f := &fake{role: false}
	d := Decide(RegisterNamespace, &Config{Retention: days(7)}, f.steps())
	if d.Allowed || f.asked != 1 || len(f.audited) != 1 || f.audited[0].Allowed {
		t.Fatalf("got %+v, audited %+v", d, f.audited)
	}
}

func TestOtherNamespaceChangesAreRefusedWithoutAskingTheRole(t *testing.T) {
	for _, api := range []string{
		operatorService + "DeleteNamespace",
		operatorService + "AddSearchAttributes",
		workflowService + "DeprecateNamespace",
		workflowService + "CreateWorkflowRule",
		adminService + "AddOrUpdateRemoteCluster",
	} {
		f := &fake{role: true}
		d := Decide(api, &Config{}, f.steps())
		if d.Allowed || f.asked != 0 || len(f.audited) != 1 {
			t.Fatalf("%s: got %+v, role asked %d, audited %+v", api, d, f.asked, f.audited)
		}
	}
}

func TestAnUnclassedAPIIsRefusedAndAudited(t *testing.T) {
	f := &fake{role: true}
	d := Decide("/temporal.api.workflowservice.v1.WorkflowService/SomethingNew", &Config{}, f.steps())
	if d.Allowed || f.asked != 0 || len(f.audited) != 1 {
		t.Fatalf("got %+v", d)
	}
}

func TestEveryOtherAPIIsTheRolesAloneAndNotAudited(t *testing.T) {
	for _, role := range []bool{true, false} {
		f := &fake{role: role}
		d := Decide(workflowService+"StartWorkflowExecution", &Config{}, f.steps())
		if d.Allowed != role || f.asked != 1 || len(f.audited) != 0 {
			t.Fatalf("role %v: got %+v, audited %+v", role, d, f.audited)
		}
	}
}

func TestNexusRoutesAreClosedWithoutAnAuditRecord(t *testing.T) {
	for _, api := range NexusHTTP {
		f := &fake{role: true}
		d := Decide(api, nil, f.steps())
		if d.Allowed || f.asked != 0 || len(f.audited) != 0 || Classify(api) != Closed {
			t.Fatalf("%s: got %+v, role asked %d, audited %+v", api, d, f.asked, f.audited)
		}
	}
}

func lines(t *testing.T, path string) map[string]bool {
	t.Helper()
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	found := map[string]bool{}
	for scanner := bufio.NewScanner(file); scanner.Scan(); {
		if line := strings.TrimSpace(scanner.Text()); line != "" {
			found[line] = true
		}
	}
	return found
}

// The table classes exactly the RPCs of v1.32.0's WorkflowService, OperatorService and AdminService (from their
// generated definitions, testdata/v1.32.0-rpcs.txt), the health and reflection services the frontend also serves,
// and the API names its Nexus HTTP routes authorize (service/frontend/configs/quotas.go,
// testdata/v1.32.0-nexus-http.txt). The build's descriptor test (internal/authz) checks the gRPC ones against the
// compiled-in services.
func TestTheTableClassesEveryRPCOfThePinnedServer(t *testing.T) {
	want := lines(t, "testdata/v1.32.0-rpcs.txt")
	nexus := lines(t, "testdata/v1.32.0-nexus-http.txt")
	if len(nexus) != len(NexusHTTP) {
		t.Fatalf("NexusHTTP %v, the source's %v", NexusHTTP, nexus)
	}
	for _, api := range NexusHTTP {
		if !nexus[api] {
			t.Fatalf("NexusHTTP names %s, the source doesn't", api)
		}
		want[api] = true
	}
	for _, api := range Served {
		want[api] = true
	}
	var missing, extra []string
	for api := range want {
		if Classify(api) == Unclassed {
			missing = append(missing, api)
		}
	}
	for api := range Table() {
		if !want[api] {
			extra = append(extra, api)
		}
	}
	sort.Strings(missing)
	sort.Strings(extra)
	if len(missing) > 0 || len(extra) > 0 {
		t.Fatalf("unclassed: %v\nnot served: %v", missing, extra)
	}
}

func TestAnInspectedCallWhoseRequestCantBeReadIsRefused(t *testing.T) {
	// an UpdateNamespace of a type the adapter doesn't know would otherwise pass on the current configuration
	for _, api := range []string{RegisterNamespace, UpdateNamespace} {
		f := &fake{role: true, current: Config{Retention: days(7)}}
		d := Decide(api, nil, f.steps())
		if d.Allowed || len(f.audited) != 1 || f.asked != 0 {
			t.Fatalf("%s: got %+v, audited %+v, role asked %d", api, d, f.audited, f.asked)
		}
	}
}
