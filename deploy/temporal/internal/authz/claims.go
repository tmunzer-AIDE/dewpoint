// SPDX-License-Identifier: Apache-2.0

package authz

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"go.temporal.io/server/common/authorization"
	"go.temporal.io/server/common/primitives"
)

// CertClaims is configuration A's claim mapper (mTLS only): a verified client certificate's common name mapped to its
// permissions, in Temporal's JWT vocabulary (`temporal-system:admin` for the cluster, `<namespace>:write`, …), from a
// JSON file read at startup: {"<common name>": ["<namespace or temporal-system>:<read|write|worker|admin>", …]}. A
// name it doesn't list has no role. Temporal sets the subject only from a verified chain, so an unverified
// certificate is no one. A bare "system" scope is refused at startup: Temporal's JWT mapper would read it as a
// namespace of that name, never the cluster (R3-B's lesson), so the two mappers never disagree on it.
type CertClaims struct {
	byName map[string][]permission
}

type permission struct {
	namespace string // primitives.SystemLocalNamespace (temporal-system): the cluster
	role      authorization.Role
}

var roles = map[string]authorization.Role{
	"read": authorization.RoleReader, "write": authorization.RoleWriter,
	"worker": authorization.RoleWorker, "admin": authorization.RoleAdmin,
}

var _ authorization.ClaimMapper = (*CertClaims)(nil)

// LoadCertClaims reads the roles file; a permission it can't parse fails startup rather than being skipped.
func LoadCertClaims(path string) (*CertClaims, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var listed map[string][]string
	if err := json.Unmarshal(raw, &listed); err != nil {
		return nil, fmt.Errorf("the certificate roles file isn't a JSON object of lists: %w", err)
	}
	m := &CertClaims{byName: map[string][]permission{}}
	for name, permissions := range listed {
		for _, p := range permissions {
			namespace, roleName, ok := strings.Cut(p, ":")
			role, known := roles[strings.ToLower(roleName)]
			if !ok || !known || namespace == "" {
				return nil, fmt.Errorf("certificate %q: permission %q isn't <namespace or %s>:<role>", name, p,
					primitives.SystemLocalNamespace)
			}
			if strings.EqualFold(namespace, "system") {
				return nil, fmt.Errorf("certificate %q: permission %q: the cluster's scope is %s, as Temporal's JWT "+
					"mapper reads it", name, p, primitives.SystemLocalNamespace)
			}
			m.byName[name] = append(m.byName[name], permission{namespace, role})
		}
	}
	return m, nil
}

func (m *CertClaims) GetClaims(info *authorization.AuthInfo) (*authorization.Claims, error) {
	claims := &authorization.Claims{AuthType: "mtls"}
	if info == nil || info.TLSSubject == nil {
		return claims, nil
	}
	claims.Subject = info.TLSSubject.CommonName
	for _, p := range m.byName[claims.Subject] {
		if p.namespace == primitives.SystemLocalNamespace {
			claims.System |= p.role
			continue
		}
		if claims.Namespaces == nil {
			claims.Namespaces = map[string]authorization.Role{}
		}
		claims.Namespaces[p.namespace] |= p.role
	}
	return claims, nil
}

// AuthInfoRequired: a call with neither a certificate nor a header gets no claims at all.
func (m *CertClaims) AuthInfoRequired() bool { return true }
