// SPDX-License-Identifier: Apache-2.0

package authz

import (
	"context"
	"testing"

	taskqueuepb "go.temporal.io/api/taskqueue/v1"
	"go.temporal.io/api/workflowservice/v1"
	"go.temporal.io/server/common/authorization"

	"dewpoint.local/temporal-server/internal/startcheck"
)

const (
	engine = "dewpoint-engine"
	api    = "/temporal.api.workflowservice.v1.WorkflowService/"
)

type checker struct {
	verdict startcheck.Verdict
	asked   [][2]string
}

func (c *checker) Check(_ context.Context, workflowID, requestID string) startcheck.Verdict {
	c.asked = append(c.asked, [2]string{workflowID, requestID})
	return c.verdict
}

var writer = &authorization.Claims{Subject: "dewpoint-dispatcher", AuthType: "jwt",
	Namespaces: map[string]authorization.Role{"default": authorization.RoleWriter}}

func start(queue string) *authorization.CallTarget {
	return &authorization.CallTarget{APIName: api + "StartWorkflowExecution", Namespace: "default",
		Request: &workflowservice.StartWorkflowExecutionRequest{Namespace: "default", WorkflowId: "t:a:run:b",
			RequestId: "c", TaskQueue: &taskqueuepb.TaskQueue{Name: queue}}}
}

func checked(c *checker) *Authorizer {
	a := authorizer(&trail{}, namespaces{})
	a.Starts = &StartCheck{Checker: c, Queue: engine}
	return a
}

func TestAnEngineStartIsCheckedAfterTheRoleAndDeniedWithAFixedReason(t *testing.T) {
	for _, c := range []struct {
		verdict  startcheck.Verdict
		decision authorization.Decision
		reason   string
	}{
		{startcheck.Allow, authorization.DecisionAllow, ""},
		{startcheck.NotPermitted, authorization.DecisionDeny, startcheck.ReasonNotPermitted},
		{startcheck.Unavailable, authorization.DecisionDeny, startcheck.ReasonUnavailable},
	} {
		check := &checker{verdict: c.verdict}
		result, err := checked(check).Authorize(context.Background(), writer, start(engine))
		if err != nil {
			t.Fatalf("%v: an error, never a denial's reason: %v", c.verdict, err)
		}
		if result.Decision != c.decision || result.Reason != c.reason {
			t.Fatalf("%v: %v %q", c.verdict, result.Decision, result.Reason)
		}
		if len(check.asked) != 1 || check.asked[0] != [2]string{"t:a:run:b", "c"} {
			t.Fatalf("%v: asked %v", c.verdict, check.asked)
		}
	}
}

func TestEachAttemptIsCheckedAfresh(t *testing.T) {
	check := &checker{verdict: startcheck.Allow}
	a := checked(check)
	for range 2 {
		if _, err := a.Authorize(context.Background(), writer, start(engine)); err != nil {
			t.Fatal(err)
		}
	}
	if len(check.asked) != 2 {
		t.Fatalf("asked %d times", len(check.asked))
	}
}

func TestAStartElsewhereOrWithoutTheRoleIsntChecked(t *testing.T) {
	check := &checker{verdict: startcheck.NotPermitted}
	result, err := checked(check).Authorize(context.Background(), writer, start("dewpoint-admission"))
	if err != nil || result.Decision != authorization.DecisionAllow || len(check.asked) != 0 {
		t.Fatalf("another queue: %v %v asked %v", result.Decision, err, check.asked)
	}
	nobody := &authorization.Claims{Subject: "nobody", AuthType: "jwt"}
	result, err = checked(check).Authorize(context.Background(), nobody, start(engine))
	if err != nil || result.Decision != authorization.DecisionDeny || len(check.asked) != 0 {
		t.Fatalf("no role: %v %v asked %v", result.Decision, err, check.asked)
	}
}

func TestOtherWaysToStartAnEngineRootAreNotPermitted(t *testing.T) {
	check := &checker{verdict: startcheck.Allow}
	queue := &taskqueuepb.TaskQueue{Name: engine}
	for name, target := range map[string]*authorization.CallTarget{
		"signal-with-start": {APIName: api + "SignalWithStartWorkflowExecution", Namespace: "default",
			Request: &workflowservice.SignalWithStartWorkflowExecutionRequest{Namespace: "default",
				WorkflowId: "t:a:run:b", TaskQueue: queue}},
		"multi-operation": {APIName: api + "ExecuteMultiOperation", Namespace: "default",
			Request: &workflowservice.ExecuteMultiOperationRequest{Namespace: "default",
				Operations: []*workflowservice.ExecuteMultiOperationRequest_Operation{{
					Operation: &workflowservice.ExecuteMultiOperationRequest_Operation_StartWorkflow{
						StartWorkflow: &workflowservice.StartWorkflowExecutionRequest{WorkflowId: "t:a:run:b",
							TaskQueue: queue}}}}}},
	} {
		result, err := checked(check).Authorize(context.Background(), writer, target)
		if err != nil || result.Decision != authorization.DecisionDeny ||
			result.Reason != startcheck.ReasonNotPermitted {
			t.Fatalf("%s: %v %q %v", name, result.Decision, result.Reason, err)
		}
	}
	if len(check.asked) != 0 {
		t.Fatalf("asked %v", check.asked)
	}
}

func TestWithTheCheckOffNothingIsChecked(t *testing.T) {
	a := authorizer(&trail{}, namespaces{}) // Starts nil: only ever by an explicit `off`
	result, err := a.Authorize(context.Background(), writer, start(engine))
	if err != nil || result.Decision != authorization.DecisionAllow {
		t.Fatalf("%v %v", result.Decision, err)
	}
}
