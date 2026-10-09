// SPDX-License-Identifier: Apache-2.0

package main

import (
	"testing"

	"google.golang.org/protobuf/reflect/protoreflect"

	"dewpoint.local/temporal-server/internal/policy"
)

func TestARequestNamesTheNamespaceWhenItHasTheField(t *testing.T) {
	request, _, err := Request("/temporal.api.operatorservice.v1.OperatorService/DeleteNamespace", "proof-ns")
	if err != nil {
		t.Fatal(err)
	}
	if got := request.Get(request.Descriptor().Fields().ByName("namespace")).String(); got != "proof-ns" {
		t.Fatalf("namespace %q", got)
	}
	// a cluster-level request has no namespace to name
	request, _, err = Request("/temporal.server.api.adminservice.v1.AdminService/AddOrUpdateRemoteCluster", "proof-ns")
	if err != nil {
		t.Fatal(err)
	}
	if request.Descriptor().Fields().ByName(protoreflect.Name("namespace")) != nil {
		t.Fatal("AddOrUpdateRemoteCluster has a namespace field")
	}
}

func TestTheRefusedSweepCoversEveryRefusedRPC(t *testing.T) {
	swept := map[string]bool{}
	for _, api := range Sweep(policy.Refused) {
		swept[api] = true
		if _, _, err := Request(api, "n"); err != nil {
			t.Errorf("%s: %v", api, err)
		}
	}
	for api, class := range policy.Table() {
		if class == policy.Refused && !swept[api] {
			t.Errorf("not swept: %s", api)
		}
	}
}
