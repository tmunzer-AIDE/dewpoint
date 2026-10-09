// SPDX-License-Identifier: Apache-2.0

package authz

import (
	"path/filepath"
	"strings"
	"testing"

	"go.temporal.io/server/common/config"
)

func load(t *testing.T, name string) *config.Config {
	t.Helper()
	cfg, err := config.Load(config.WithConfigFile(filepath.Join("..", "..", "config", name)))
	if err != nil {
		t.Fatal(err)
	}
	return cfg
}

func TestTheShippedConfigurationsPass(t *testing.T) {
	if err := CheckConfig(load(t, "mtls.yaml"), ModeMTLS); err != nil {
		t.Fatalf("A: %v", err)
	}
	if err := CheckConfig(load(t, "jwt.yaml"), ModeJWT); err != nil {
		t.Fatalf("B: %v", err)
	}
}

func TestAConfigurationTheRulesCantHoldOnIsRefused(t *testing.T) {
	cases := map[string]func(*config.Config) string{
		"cluster archival": func(c *config.Config) string {
			c.Archival.History.State = "enabled"
			return "archival.history.state"
		},
		"a new namespace's archival": func(c *config.Config) string {
			c.NamespaceDefaults.Archival.Visibility.State = ""
			return "namespaceDefaults.archival.visibility.state"
		},
		"no internal frontend": func(c *config.Config) string {
			delete(c.Services, "internal-frontend")
			return "internal-frontend"
		},
		"internode without client certificates": func(c *config.Config) string {
			c.Global.TLS.Internode.Server.RequireClientAuth = false
			return "internode"
		},
		"A without client certificates": func(c *config.Config) string {
			c.Global.TLS.Frontend.Server.RequireClientAuth = false
			return "mtls:"
		},
	}
	for name, breakIt := range cases {
		t.Run(name, func(t *testing.T) {
			cfg := load(t, "mtls.yaml")
			want := breakIt(cfg)
			if err := CheckConfig(cfg, ModeMTLS); err == nil || !strings.Contains(err.Error(), want) {
				t.Fatalf("got %v, want %q", err, want)
			}
		})
	}
	b := load(t, "jwt.yaml")
	b.Global.Authorization.Audience = ""
	if err := CheckConfig(b, ModeJWT); err == nil {
		t.Fatal("B without an audience")
	}
	if err := CheckConfig(load(t, "jwt.yaml"), "both"); err == nil {
		t.Fatal("an unknown mode")
	}
}
