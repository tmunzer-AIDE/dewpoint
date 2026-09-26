# SPDX-License-Identifier: Apache-2.0
import uuid
from dataclasses import dataclass
from typing import Any, Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Diagnostic:
    """One validation finding. `code` is stable and documented; `message` is shown to the author."""

    code: str
    message: str
    node: uuid.UUID | None = None
    field: str | None = None  # JSON pointer inside the node's config, or /settings/...
    fix: str | None = None
    severity: Severity = "error"

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "node": str(self.node) if self.node else None,
            "field": self.field,
            "fix": self.fix,
            "severity": self.severity,
        }
