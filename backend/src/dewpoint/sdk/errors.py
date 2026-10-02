# SPDX-License-Identifier: Apache-2.0
"""Errors a node raises. `code` is a stable, documented identifier; `message` must be safe to show users."""


class NodeError(Exception):
    """A node's failure (engine 2b spec §3.7, §6.7). Its step shows the code only when it's a constant of the plugin's
    code and a dotted lowercase identifier (`mist.rate_limited`), else `node_failed`; and the message only when it's
    a constant of the plugin's code, else a generic one: a value it quotes may be a secret the run doesn't know yet.
    So write `FatalError("mist.not_found", "The site doesn't exist.")`, not `f"Site {site_id} doesn't exist."`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RetryableError(NodeError):
    """Transient: the engine retries it within the step's retry policy."""


class FatalError(NodeError):
    """Permanent: retrying can't help. The step fails and follows its error policy."""


class OutcomeUnknownError(NodeError):
    """The request may have been delivered. The engine never retries it automatically (`outcome_unknown`)."""
