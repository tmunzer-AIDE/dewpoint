// SPDX-License-Identifier: Apache-2.0

package authz

import (
	"context"
	"errors"
	"sync"

	"go.temporal.io/server/common/persistence"
	persistenceclient "go.temporal.io/server/common/persistence/client"
	"go.temporal.io/server/common/primitives"

	"dewpoint.local/temporal-server/internal/policy"
)

// Persistence reads a namespace's configuration straight from Temporal's store, not from the frontend's namespace
// cache, which can be seconds old. Its Provider wraps Temporal's persistence factory provider
// (temporal.WithPersistenceFactoryProvider) and keeps the first frontend's factory.
type Persistence struct {
	mu      sync.Mutex
	factory persistenceclient.Factory
	manager persistence.MetadataManager
}

var _ Namespaces = (*Persistence)(nil)

func (p *Persistence) Provider(params persistenceclient.NewFactoryParams) persistenceclient.Factory {
	factory := persistenceclient.FactoryProvider(params)
	if params.ServiceName == primitives.FrontendService || params.ServiceName == primitives.InternalFrontendService {
		p.mu.Lock()
		if p.factory == nil {
			p.factory = factory
		}
		p.mu.Unlock()
	}
	return factory
}

func (p *Persistence) metadata() (persistence.MetadataManager, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.manager == nil {
		if p.factory == nil {
			return nil, errors.New("no frontend persistence yet")
		}
		manager, err := p.factory.NewMetadataManager()
		if err != nil {
			return nil, err
		}
		p.manager = manager
	}
	return p.manager, nil
}

func (p *Persistence) Config(ctx context.Context, name string) (policy.Config, error) {
	manager, err := p.metadata()
	if err != nil {
		return policy.Config{}, err
	}
	found, err := manager.GetNamespace(ctx, &persistence.GetNamespaceRequest{Name: name})
	if err != nil {
		return policy.Config{}, err
	}
	c := found.Namespace.GetConfig()
	return policy.Config{Retention: retention(c.GetRetention()), History: archival(c.GetHistoryArchivalState()),
		Visibility: archival(c.GetVisibilityArchivalState())}, nil
}
