# SPDX-License-Identifier: Apache-2.0
from enum import StrEnum


class P(StrEnum):
    TENANT_VIEW = "tenant.view"
    TENANT_MANAGE = "tenant.manage"
    MEMBER_VIEW = "member.view"
    MEMBER_MANAGE = "member.manage"
    CONNECTION_VIEW = "connection.view"
    CONNECTION_USE = "connection.use"
    CONNECTION_MANAGE = "connection.manage"
    AUDIT_VIEW = "audit.view"
    WORKFLOW_VIEW = "workflow.view"
    WORKFLOW_EDIT = "workflow.edit"
    WORKFLOW_PUBLISH = "workflow.publish"
    WORKFLOW_DECLASSIFY = "workflow.declassify"  # publishing a version that lists declassified sites (2b §4.3)
    RUN_START = "run.start"
    RUN_VIEW = "run.view"
    APPROVAL_DECIDE = "approval.decide"
    AGENT_GRANT = "agent.grant"


_VIEWER = frozenset({P.TENANT_VIEW, P.WORKFLOW_VIEW, P.RUN_VIEW, P.CONNECTION_VIEW, P.MEMBER_VIEW})
_OPERATOR = _VIEWER | {P.RUN_START, P.APPROVAL_DECIDE}
_EDITOR = _OPERATOR | {P.WORKFLOW_EDIT, P.WORKFLOW_PUBLISH, P.CONNECTION_USE}
_ADMIN = _EDITOR | {
    P.TENANT_MANAGE,
    P.MEMBER_MANAGE,
    P.CONNECTION_MANAGE,
    P.AUDIT_VIEW,
    P.AGENT_GRANT,
    P.WORKFLOW_DECLASSIFY,
}

ROLE_PERMISSIONS: dict[str, frozenset[P]] = {
    "viewer": _VIEWER,
    "operator": _OPERATOR,
    "editor": _EDITOR,
    "admin": _ADMIN,
    "owner": _ADMIN,
}
