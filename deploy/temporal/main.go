// SPDX-License-Identifier: Apache-2.0

// Command temporal-server is D12's production-like Temporal target (2b-4b M4): Temporal server v1.32.0 as a library,
// every service in one process, with Dewpoint's authorizer (internal/authz) and either a client certificate's roles
// (configuration A, mutual TLS only) or Temporal's JWT claim mapper (configuration B, a bearer token only).
//
//	temporal-server              run the server
//	temporal-server inventory    print D12.1's inventory: this binary's identity and its build context's, the
//	                             frontend's every RPC and its class, and every listener the configuration opens
//
// Settings (environment): DEWPOINT_TEMPORAL_CONFIG (the server's YAML), DEWPOINT_AUTHZ_CLAIMS (mtls or jwt),
// DEWPOINT_AUTHZ_CERT_ROLES (mtls: the roles file), DEWPOINT_AUTHZ_AUDIT_BUCKET, _PREFIX, _REGION, _ENDPOINT (the
// audit trail; its credentials are the standard AWS ones, a shared credentials file preferred), and
// DEWPOINT_AUTHZ_AUDIT_FAULTS (real-target qualification only: a file naming the namespaces whose audit writes fail).
// The start check (internal/startcheck): DEWPOINT_AUTHZ_START_CHECK, on or off, required, never off by omission; on
// needs DEWPOINT_AUTHZ_START_CHECK_DSN_FILE (Dewpoint's database, as the start check's role), _DEADLINE and _QUEUE
// (the engine's task queue). The inventory names the mode as configured: a prerequisite, not proof of the boundary.
// Turned on last: only once Dewpoint's migration 0052 is applied and every dispatcher runs a build that sends its
// recorded start request id. An older dispatcher sends without one, so every start it sends is denied, and it takes
// each denial for a refusal: its requests would end dead after ten (the rollout order, the owner's ruling 2026-10-10).
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"runtime"
	"runtime/debug"

	"go.temporal.io/server/common/authorization"
	"go.temporal.io/server/common/config"
	"go.temporal.io/server/common/headers"
	"go.temporal.io/server/common/log"
	"go.temporal.io/server/common/log/tag"
	"go.temporal.io/server/temporal"

	"dewpoint.local/temporal-server/internal/audit"
	"dewpoint.local/temporal-server/internal/auditbucket"
	"dewpoint.local/temporal-server/internal/authz"
	"dewpoint.local/temporal-server/internal/policy"
	"dewpoint.local/temporal-server/internal/startcheck"
)

func setting(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func fail(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "temporal-server: "+format+"\n", args...)
	os.Exit(1)
}

// source is the identity of the build context this binary was built from, stamped by the image build (`-X
// main.source`; the Dockerfile): the proofs refuse an image whose inventory doesn't name this tree's.
var source = "unrecorded"

// binaryHash is this executable's SHA-256: the server build's identity in each audit record and the inventory.
func binaryHash() string {
	path, err := os.Executable()
	if err != nil {
		fail("can't find this executable: %T", err)
	}
	file, err := os.Open(path)
	if err != nil {
		fail("can't read this executable: %T", err)
	}
	defer file.Close()
	sum := sha256.New()
	if _, err := io.Copy(sum, file); err != nil {
		fail("can't read this executable: %T", err)
	}
	return "sha256:" + hex.EncodeToString(sum.Sum(nil))
}

func main() {
	cfg, err := config.Load(config.WithConfigFile(setting("DEWPOINT_TEMPORAL_CONFIG", "/etc/temporal/config.yaml")))
	if err != nil {
		fail("the configuration can't be loaded: %v", err)
	}
	if len(os.Args) > 1 && os.Args[1] == "inventory" {
		inventory(cfg)
		return
	}
	mode := os.Getenv("DEWPOINT_AUTHZ_CLAIMS")
	if err := authz.CheckConfig(cfg, mode); err != nil {
		fail("refused: %v", err)
	}
	starts, err := startcheck.FromEnv(os.Getenv, os.ReadFile)
	if err != nil {
		fail("refused: %v", err)
	}
	bucket := os.Getenv("DEWPOINT_AUTHZ_AUDIT_BUCKET")
	if bucket == "" {
		fail("refused: DEWPOINT_AUTHZ_AUDIT_BUCKET is required (the authorizer's audit trail)")
	}
	logger := log.NewZapLogger(log.BuildZapLogger(cfg.Log))
	client, err := auditbucket.NewClient(context.Background(), setting("DEWPOINT_AUTHZ_AUDIT_REGION", "us-east-1"),
		os.Getenv("DEWPOINT_AUTHZ_AUDIT_ENDPOINT"))
	if err != nil {
		fail("the audit trail's client can't be made: %T", err)
	}
	faults := os.Getenv("DEWPOINT_AUTHZ_AUDIT_FAULTS")
	if faults != "" {
		logger.Warn("audit write failures will be injected for the namespaces the fault file names",
			tag.NewStringTag("fault-file", faults))
	}
	writer := audit.WithFaults(auditbucket.Writer{Client: client, Bucket: bucket,
		Prefix: setting("DEWPOINT_AUTHZ_AUDIT_PREFIX", "dewpoint/")}, faults)
	namespaces := &authz.Persistence{}
	authorizer := &authz.Authorizer{
		Delegate: authorization.NewDefaultAuthorizer(), Namespaces: namespaces, Audit: writer,
		NewNamespace: policy.Config{History: policy.ArchivalDisabled, Visibility: policy.ArchivalDisabled},
		Server:       binaryHash(), Logger: logger,
	}
	if starts.Mode == startcheck.ModeOn {
		pool, err := startcheck.NewPool(context.Background(), starts) // lazy: an unreachable database denies per start
		if err != nil {
			fail("refused: %v", err)
		}
		authorizer.Starts = &authz.StartCheck{Checker: startcheck.DB{Pool: pool, Deadline: starts.Deadline},
			Queue: starts.Queue}
	} else {
		logger.Warn("the start check is off (" + startcheck.EnvMode + "=off): engine-queue starts aren't checked, " +
			"and this server claims no admission boundary")
	}
	var claims authorization.ClaimMapper
	options := []temporal.ServerOption{}
	switch mode {
	case authz.ModeMTLS:
		claims, err = authz.LoadCertClaims(os.Getenv("DEWPOINT_AUTHZ_CERT_ROLES"))
		if err != nil {
			fail("refused: the certificate roles (DEWPOINT_AUTHZ_CERT_ROLES): %v", err)
		}
	case authz.ModeJWT:
		auth := &cfg.Global.Authorization
		claims = authorization.NewDefaultJWTClaimMapper(authorization.NewDefaultTokenKeyProvider(auth, logger), auth, logger)
		audience, err := authorization.GetAudienceMapperFromConfig(auth)
		if err != nil {
			fail("refused: the JWT audience: %v", err)
		}
		options = append(options, temporal.WithAudienceGetter(func(*config.Config) authorization.JWTAudienceMapper {
			return audience
		}))
	}
	options = append(options,
		temporal.ForServices(temporal.Services), // the internal frontend included (CheckConfig requires it)
		temporal.WithConfig(cfg),
		temporal.WithLogger(logger),
		temporal.InterruptOn(temporal.InterruptCh()),
		temporal.WithAuthorizer(authorizer),
		temporal.WithClaimMapper(func(*config.Config) authorization.ClaimMapper { return claims }),
		temporal.WithPersistenceFactoryProvider(namespaces.Provider),
	)
	server, err := temporal.NewServer(options...)
	if err != nil {
		fail("the server can't be made: %v", err)
	}
	if err := server.Start(); err != nil {
		fail("the server stopped: %v", err)
	}
}

func inventory(cfg *config.Config) {
	var modules []string
	if info, ok := debug.ReadBuildInfo(); ok {
		for _, m := range info.Deps {
			modules = append(modules, m.Path+"@"+m.Version+" "+m.Sum)
		}
	}
	out := json.NewEncoder(os.Stdout)
	out.SetIndent("", "  ")
	if err := out.Encode(map[string]any{
		"binary":         binaryHash(),
		"source":         source,
		"server_version": headers.ServerVersion,
		"go_version":     runtime.Version(),
		"modules":        modules,
		"rpcs":           authz.RPCs(),
		"endpoints":      authz.Endpoints(cfg),
		"start_check":    startcheck.Reported(os.Getenv),
	}); err != nil {
		fail("the inventory can't be written: %T", err)
	}
}
