# SPDX-License-Identifier: Apache-2.0
"""A connection's config checked twice, which must agree: by the API, against the manifest's JSON Schema alone (it
never runs plugin code), and by the worker, with the plugin's model (`unseal`). And values near the edges of the rules
configs use, taken or refused, for a property test of the two."""

from collections.abc import Mapping
from typing import Any

from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from dewpoint.core.connections.declared import DeclaredType, InvalidValueError

# Nothing, or a tail a schema pattern's `$` (Python's, which takes a final newline) might let through.
ENDS = st.one_of(st.just(""), st.sampled_from(["\n", "\r\n", "\r", " ", "."]))
# Host names of two or more clean labels (up to one past a label's 63 characters), or of labels of any form.
LABEL, ANY_LABEL = st.text(alphabet="ab9", min_size=1, max_size=64), st.text(alphabet="aZ9-é", max_size=64)
NAMES = st.one_of(st.lists(LABEL, min_size=2, max_size=4), st.lists(LABEL | ANY_LABEL, min_size=1, max_size=4))
HOSTS = st.builds(lambda labels, end: ".".join(labels) + end, NAMES, ENDS)
# Text of printable ASCII, or of any character, then an end.
PRINTABLE = st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E), max_size=30)
TEXTS = st.builds(str.__add__, PRINTABLE | st.text(max_size=30), ENDS)


def taken(model: type[BaseModel], declared: DeclaredType, value: Mapping[str, Any]) -> tuple[bool, bool]:
    """Whether the worker's model and the API's schema each take a config."""
    try:
        model.model_validate(value)
        worker = True
    except ValidationError:
        worker = False
    try:
        declared.config(value)
        api = True
    except InvalidValueError:
        api = False
    return worker, api
