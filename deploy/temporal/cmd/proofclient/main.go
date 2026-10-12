// SPDX-License-Identifier: Apache-2.0

// Command proofclient is D12's exhaustive caller (2b-4b M4), for the gRPC calls the Python SDK can't make: every RPC
// of a class (AdminService's among them), and namespace changes on the internal frontend, which only a client inside
// the server's network namespace with the internode certificate reaches.
//
//	proofclient sweep --class refused --namespace N [connection]   each RPC of the class, one JSON line per answer
//	proofclient register --namespace N --retention-days D [connection]
//	proofclient update --namespace N --retention-days D [connection]
//
// Connection: --address, --ca, --server-name, and --cert with --key (mutual TLS) or --token-file (a bearer token,
// read from the file, never an argument). A request's `namespace` field, when it has one, names N: Temporal's
// namespace validator runs before the authorizer, so a request without one would never reach it.
package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	namespacepb "go.temporal.io/api/namespace/v1"
	"go.temporal.io/api/workflowservice/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/reflect/protoregistry"
	"google.golang.org/protobuf/types/dynamicpb"
	"google.golang.org/protobuf/types/known/durationpb"

	"dewpoint.local/temporal-server/internal/authz"
	"dewpoint.local/temporal-server/internal/policy"
)

type connection struct {
	address, ca, serverName, cert, key, tokenFile string
}

func (c connection) dial() (*grpc.ClientConn, error) {
	roots := x509.NewCertPool()
	pem, err := os.ReadFile(c.ca)
	if err != nil || !roots.AppendCertsFromPEM(pem) {
		return nil, errors.New("the CA file can't be read")
	}
	config := &tls.Config{RootCAs: roots, ServerName: c.serverName, MinVersion: tls.VersionTLS12}
	if c.cert != "" {
		pair, err := tls.LoadX509KeyPair(c.cert, c.key)
		if err != nil {
			return nil, errors.New("the client certificate can't be read")
		}
		config.Certificates = []tls.Certificate{pair}
	}
	return grpc.NewClient(c.address, grpc.WithTransportCredentials(credentials.NewTLS(config)))
}

func (c connection) context() (context.Context, context.CancelFunc, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	if c.tokenFile == "" {
		return ctx, cancel, nil
	}
	token, err := os.ReadFile(c.tokenFile)
	if err != nil {
		cancel()
		return nil, nil, errors.New("the token file can't be read")
	}
	return metadata.AppendToOutgoingContext(ctx, "authorization", "Bearer "+strings.TrimSpace(string(token))), cancel, nil
}

// Request is an empty request for `api` with its namespace field, if any, set to `namespace`; and its answer.
func Request(api, namespace string) (*dynamicpb.Message, *dynamicpb.Message, error) {
	service, method, ok := strings.Cut(strings.TrimPrefix(api, "/"), "/")
	if !ok {
		return nil, nil, fmt.Errorf("not a gRPC method: %s", api)
	}
	found, err := protoregistry.GlobalFiles.FindDescriptorByName(protoreflect.FullName(service))
	if err != nil {
		return nil, nil, err
	}
	m := found.(protoreflect.ServiceDescriptor).Methods().ByName(protoreflect.Name(method))
	if m == nil {
		return nil, nil, fmt.Errorf("no method %s", api)
	}
	request := dynamicpb.NewMessage(m.Input())
	if field := m.Input().Fields().ByName("namespace"); field != nil && field.Kind() == protoreflect.StringKind {
		request.Set(field, protoreflect.ValueOfString(namespace))
	}
	return request, dynamicpb.NewMessage(m.Output()), nil
}

// Sweep is every gRPC RPC of `class`, sorted.
func Sweep(class policy.Class) []string {
	var apis []string
	for _, rpc := range authz.RPCs() {
		if rpc.Kind == "grpc" && rpc.Class == class.String() {
			apis = append(apis, rpc.API)
		}
	}
	sort.Strings(apis)
	return apis
}

func main() {
	if len(os.Args) < 2 {
		fail("usage: proofclient sweep|register|update [flags]")
	}
	flags := flag.NewFlagSet(os.Args[1], flag.ExitOnError)
	var c connection
	flags.StringVar(&c.address, "address", "", "the frontend's host:port")
	flags.StringVar(&c.ca, "ca", "", "the CA the server's certificate is verified against")
	flags.StringVar(&c.serverName, "server-name", "", "the name verified in the server's certificate")
	flags.StringVar(&c.cert, "cert", "", "a client certificate (mutual TLS)")
	flags.StringVar(&c.key, "key", "", "its key")
	flags.StringVar(&c.tokenFile, "token-file", "", "a file holding a bearer token")
	namespace := flags.String("namespace", "", "the namespace")
	class := flags.String("class", "refused", "sweep: the class (refused or delegated)")
	days := flags.Int("retention-days", 0, "register or update: the retention in days")
	_ = flags.Parse(os.Args[2:])
	conn, err := c.dial()
	if err != nil {
		fail("%v", err)
	}
	defer conn.Close()
	out := json.NewEncoder(os.Stdout)
	switch os.Args[1] {
	case "sweep":
		wanted := map[string]policy.Class{"refused": policy.Refused, "delegated": policy.Delegated}[*class]
		if wanted == policy.Unclassed {
			fail("--class must be refused or delegated")
		}
		for _, api := range Sweep(wanted) {
			request, answer, err := Request(api, *namespace)
			if err != nil {
				fail("%v", err)
			}
			ctx, cancel, err := c.context()
			if err != nil {
				fail("%v", err)
			}
			err = conn.Invoke(ctx, api, request, answer)
			cancel()
			_ = out.Encode(map[string]string{"api": api, "code": status.Code(err).String()})
		}
	case "register", "update":
		ctx, cancel, err := c.context()
		if err != nil {
			fail("%v", err)
		}
		defer cancel()
		retention := durationpb.New(time.Duration(*days) * 24 * time.Hour)
		client := workflowservice.NewWorkflowServiceClient(conn)
		if os.Args[1] == "register" {
			_, err = client.RegisterNamespace(ctx, &workflowservice.RegisterNamespaceRequest{
				Namespace: *namespace, WorkflowExecutionRetentionPeriod: retention})
		} else {
			_, err = client.UpdateNamespace(ctx, &workflowservice.UpdateNamespaceRequest{
				Namespace: *namespace, Config: &namespacepb.NamespaceConfig{WorkflowExecutionRetentionTtl: retention}})
		}
		_ = out.Encode(map[string]string{"api": os.Args[1], "namespace": *namespace, "code": status.Code(err).String()})
	default:
		fail("unknown command %q", os.Args[1])
	}
}

func fail(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "proofclient: "+format+"\n", args...)
	os.Exit(2)
}
