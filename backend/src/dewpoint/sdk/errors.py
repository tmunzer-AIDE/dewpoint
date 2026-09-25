# SPDX-License-Identifier: Apache-2.0
"""Errors a node raises. `code` is a stable, documented identifier; `message` must be safe to show users."""


class NodeError(Exception):
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
