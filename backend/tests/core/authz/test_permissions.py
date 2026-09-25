# SPDX-License-Identifier: Apache-2.0
from itertools import pairwise

from dewpoint.core.authz.permissions import ROLE_PERMISSIONS, P


def test_role_hierarchy_is_monotonic() -> None:
    order = ["viewer", "operator", "editor", "admin", "owner"]
    for lower, higher in pairwise(order):
        assert ROLE_PERMISSIONS[lower] <= ROLE_PERMISSIONS[higher], (lower, higher)


def test_key_grants() -> None:
    assert P.CONNECTION_USE in ROLE_PERMISSIONS["editor"]
    assert P.CONNECTION_MANAGE not in ROLE_PERMISSIONS["editor"]
    assert P.MEMBER_MANAGE in ROLE_PERMISSIONS["admin"]
    assert P.AGENT_GRANT in ROLE_PERMISSIONS["admin"]
    assert P.RUN_START in ROLE_PERMISSIONS["operator"] and P.WORKFLOW_EDIT not in ROLE_PERMISSIONS["operator"]
    assert ROLE_PERMISSIONS["viewer"] == {P.TENANT_VIEW, P.WORKFLOW_VIEW, P.RUN_VIEW, P.CONNECTION_VIEW, P.MEMBER_VIEW}
