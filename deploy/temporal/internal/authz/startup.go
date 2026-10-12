// SPDX-License-Identifier: Apache-2.0

package authz

import (
	"errors"
	"strings"

	"go.temporal.io/server/common/config"
	"go.temporal.io/server/common/primitives"
)

// Claims modes: configuration A, mutual TLS only, and configuration B, a JWT bearer token only.
const (
	ModeMTLS = "mtls"
	ModeJWT  = "jwt"
)

// CheckConfig refuses a configuration the namespace rules can't hold on, before the server starts:
//   - archival other than disabled, for the cluster or as a new namespace's default (erasure requires it off);
//   - no internal frontend: the server's system workers (schedules among them) reach the frontend through it, with
//     this authorizer, rather than through the public frontend with a credential of their own; or one with an HTTP
//     API, which Temporal serves without internode TLS and grants system admin with no credential;
//   - the frontend or internode without TLS, or internode without client certificates;
//   - configuration A without client certificates required, or B without a key set and an audience.
func CheckConfig(cfg *config.Config, mode string) error {
	var problems []string
	for what, state := range map[string]string{
		"archival.history.state":                      cfg.Archival.History.State,
		"archival.visibility.state":                   cfg.Archival.Visibility.State,
		"namespaceDefaults.archival.history.state":    cfg.NamespaceDefaults.Archival.History.State,
		"namespaceDefaults.archival.visibility.state": cfg.NamespaceDefaults.Archival.Visibility.State,
	} {
		if !strings.EqualFold(state, "disabled") {
			problems = append(problems, what+" must be disabled")
		}
	}
	if internal, ok := cfg.Services[string(primitives.InternalFrontendService)]; !ok {
		problems = append(problems, "no internal-frontend service")
	} else if internal.RPC.HTTPPort != 0 {
		// Temporal serves it with the frontend's TLS and the internal claim mapper: system admin for any caller
		problems = append(problems, "internal-frontend httpPort must be unset (an HTTP API there needs no credential)")
	}
	tls := cfg.Global.TLS
	if tls.Frontend.Server.CertFile == "" {
		problems = append(problems, "the frontend has no TLS certificate")
	}
	if tls.Internode.Server.CertFile == "" || !tls.Internode.Server.RequireClientAuth {
		problems = append(problems, "internode traffic must be mutual TLS")
	}
	switch mode {
	case ModeMTLS:
		if !tls.Frontend.Server.RequireClientAuth {
			problems = append(problems, "mtls: the frontend must require client certificates")
		}
	case ModeJWT:
		auth := cfg.Global.Authorization
		if len(auth.JWTKeyProvider.KeySourceURIs) == 0 || auth.Audience == "" {
			problems = append(problems, "jwt: a key set (jwtKeyProvider.keySourceURIs) and an audience are required")
		}
	default:
		problems = append(problems, "DEWPOINT_AUTHZ_CLAIMS must be mtls or jwt")
	}
	if len(problems) > 0 {
		return errors.New(strings.Join(problems, "; "))
	}
	return nil
}
