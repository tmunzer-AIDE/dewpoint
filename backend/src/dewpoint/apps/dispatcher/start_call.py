# SPDX-License-Identifier: Apache-2.0
"""The dispatcher's start call (2b-4b M4, the start-check slice; the upgrade barrier's revisions 14 to 17).

A request's every start carries the start request id recorded with it (`run_requests.start_request_id`): Temporal keeps
a start's request id with its started event, and D12's start check matches it against the request's. The SDK builds
and seals the request itself (its arguments encoded under the workflow's serialization context, its interceptors run)
and then sets a random request id it doesn't expose; so this wraps one call of one client, the dispatcher's
`workflow_service.start_workflow_execution`, and within `sending(request_id)` replaces that request id and nothing
else. The call is then made with `retry=False`: the SDK and its core don't repeat it, so each send counted before it's
made (`CAP` at most) is one RPC attempt. Outside `sending`, and on every other client, every call is the SDK's own."""

import contextlib
import contextvars
import uuid
from collections.abc import Iterator, Mapping
from datetime import timedelta
from typing import Any

from temporalio.client import Client

CAP = 10  # a request's start sends, at most: each one RPC attempt (the owner's ruling on revision 12)
_SENDING: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar("dewpoint_start_request_id", default=None)
_INSTALLED = "_dewpoint_start_call"


def install(client: Client) -> None:
    """Wraps this client's `workflow_service.start_workflow_execution` alone, once."""
    service = client.workflow_service
    if getattr(service, _INSTALLED, False):
        return
    call = service.start_workflow_execution

    # the SDK's own signature, which its client calls by keyword (`temporalio/bridge/services_generated.py`)
    async def start_workflow_execution(req: Any, retry: bool = False, metadata: Mapping[str, str | bytes] = {},  # noqa: B006
                                       timeout: timedelta | None = None) -> Any:  # noqa: ASYNC109  # fmt: skip
        request_id = _SENDING.get()
        if request_id is None:
            return await call(req, retry=retry, metadata=metadata, timeout=timeout)
        req.request_id = str(request_id)
        return await call(req, retry=False, metadata=metadata, timeout=timeout)

    service.start_workflow_execution = start_workflow_execution  # type: ignore[method-assign]
    setattr(service, _INSTALLED, True)


@contextlib.contextmanager
def sending(request_id: uuid.UUID) -> Iterator[None]:
    """Within it, a start through an installed client carries `request_id`, as one RPC attempt."""
    token = _SENDING.set(request_id)
    try:
        yield
    finally:
        _SENDING.reset(token)
