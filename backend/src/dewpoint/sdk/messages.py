# SPDX-License-Identifier: Apache-2.0
"""The message model the chat and webhook targets render (plugins-3 D18): a title, a text, label and value fields,
link buttons and a severity. The bounds here are generous; each target renders within its own limits, cutting a value
past one and marking it (`cut`), and says which it cut."""

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MARK = "…"  # what a cut value ends with
LINK_URL = re.compile(r"https?://[^\s<>\"\\]{1,2000}")  # matched whole: a final newline can't pass as with `$`


class Severity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    CRITICAL = "critical"


class MessageField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=200)
    value: str = Field(max_length=10_000)


class Link(BaseModel):
    """A link button: http or https only, so a message never carries a script or another scheme."""

    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=200)
    url: str = Field(max_length=2000)

    @field_validator("url")
    @classmethod
    def _http(cls, value: str) -> str:
        if not LINK_URL.fullmatch(value):
            raise ValueError("a link is an http or https URL")
        return value


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=1000)
    text: str = Field(min_length=1, max_length=40_000)
    fields: list[MessageField] = Field(default_factory=list, max_length=25)
    links: list[Link] = Field(default_factory=list, max_length=10)
    severity: Severity = Severity.INFO


def cut(text: str, limit: int, *, unit: Literal["chars", "bytes"] = "chars") -> tuple[str, bool]:
    """`text` within `limit` characters (or UTF-8 bytes), ending with `MARK` when it had to be cut; whether it was."""
    if unit == "chars":
        return (text, False) if len(text) <= limit else (text[: max(0, limit - len(MARK))] + MARK, True)
    if len(text.encode()) <= limit:
        return text, False
    budget, size, kept = limit - len(MARK.encode()), 0, []
    for char in text:
        size += len(char.encode())
        if size > budget:
            break
        kept.append(char)
    return "".join(kept) + MARK, True
