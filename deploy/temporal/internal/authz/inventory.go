// SPDX-License-Identifier: Apache-2.0

package authz

import (
	"fmt"
	"sort"

	"go.temporal.io/api/operatorservice/v1"
	"go.temporal.io/api/workflowservice/v1"
	"go.temporal.io/server/api/adminservice/v1"
	"go.temporal.io/server/common/config"
	"go.temporal.io/server/common/primitives"
	"google.golang.org/grpc"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
	reflectionv1 "google.golang.org/grpc/reflection/grpc_reflection_v1"
	reflectionv1alpha "google.golang.org/grpc/reflection/grpc_reflection_v1alpha"

	"dewpoint.local/temporal-server/internal/policy"
)

// FrontendServices are the gRPC services Temporal v1.32.0's frontend registers (service/frontend/service.go), as
// compiled into this binary: D12.1's inventory is taken from these, not from a list kept by hand.
var FrontendServices = []*grpc.ServiceDesc{
	&healthpb.Health_ServiceDesc,
	&workflowservice.WorkflowService_ServiceDesc,
	&adminservice.AdminService_ServiceDesc,
	&operatorservice.OperatorService_ServiceDesc,
	&reflectionv1.ServerReflection_ServiceDesc,
	&reflectionv1alpha.ServerReflection_ServiceDesc,
}

type RPC struct {
	API   string `json:"api"`
	Kind  string `json:"kind"` // grpc, or http: a Nexus route's name, not a gRPC service's
	Class string `json:"class"`
}

// RPCs is every RPC of the frontend's services, then every API name its Nexus HTTP routes authorize, each with its
// class; Unclassed ones included, so a gap shows.
func RPCs() []RPC {
	var rpcs []RPC
	for _, service := range FrontendServices {
		var names []string
		for _, m := range service.Methods {
			names = append(names, m.MethodName)
		}
		for _, s := range service.Streams {
			names = append(names, s.StreamName)
		}
		for _, name := range names {
			api := "/" + service.ServiceName + "/" + name
			rpcs = append(rpcs, RPC{api, "grpc", policy.Classify(api).String()})
		}
	}
	for _, api := range policy.NexusHTTP {
		rpcs = append(rpcs, RPC{api, "http", policy.Classify(api).String()})
	}
	sort.Slice(rpcs, func(i, j int) bool { return rpcs[i].API < rpcs[j].API })
	return rpcs
}

type Endpoint struct {
	Service    string `json:"service"`
	Kind       string `json:"kind"` // grpc, http or membership
	Address    string `json:"address"`
	Authorized bool   `json:"authorized"` // through this authorizer
	Note       string `json:"note,omitempty"`
}

// Endpoints is every listener the configuration opens. The frontends' gRPC and HTTP go through the authorizer; the
// other services' gRPC and every membership port are internode only, mutual TLS on the container network, and inside
// the trusted platform-operator boundary (as D12b rules for the store's administrators).
func Endpoints(cfg *config.Config) []Endpoint {
	var endpoints []Endpoint
	names := make([]string, 0, len(cfg.Services))
	for name := range cfg.Services {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		rpc := cfg.Services[name].RPC
		frontend := name == string(primitives.FrontendService) || name == string(primitives.InternalFrontendService)
		at := func(port int) string { return fmt.Sprintf("%s:%d", rpc.BindOnIP, port) }
		note := ""
		if !frontend {
			note = "internode only: mutual TLS, the container network"
		} else if name == string(primitives.InternalFrontendService) {
			note = "internode mutual TLS; Temporal's internal claim mapper (system admin), this authorizer"
		}
		endpoints = append(endpoints, Endpoint{name, "grpc", at(rpc.GRPCPort), frontend, note})
		if rpc.HTTPPort != 0 {
			endpoints = append(endpoints, Endpoint{name, "http", at(rpc.HTTPPort), frontend, note})
		}
		endpoints = append(endpoints, Endpoint{name, "membership", at(rpc.MembershipPort), false,
			"internode only: the container network"})
	}
	return endpoints
}
