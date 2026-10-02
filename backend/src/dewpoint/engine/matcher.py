# SPDX-License-Identifier: Apache-2.0
"""Finding a run's secrets in text (engine 2b spec §3.5, §3.7): one Aho–Corasick automaton built once for a set of
strings, so a scan costs the text's length and the matches it finds, never its length times the number of secrets.
A secret has at least MIN_SECRET characters: shorter ones would match ordinary text everywhere."""

from collections.abc import Iterable
from typing import Any

import ahocorasick_rs

from dewpoint.engine.sensitive import MIN_SECRET


class Matcher:
    # Never the DFA the library picks for few patterns: its construction grows with a long secret's length squared,
    # and the index holds strings up to 8 MiB. The contiguous NFA builds and scans in their length.
    IMPLEMENTATION = ahocorasick_rs.Implementation.ContiguousNFA

    def __init__(self, strings: Iterable[str]) -> None:
        self.strings = tuple(sorted({s for s in strings if len(s) >= MIN_SECRET}))
        self._automaton = (
            ahocorasick_rs.AhoCorasick(
                list(self.strings),
                matchkind=ahocorasick_rs.MatchKind.Standard,  # every match, overlapping ones too (the review's M4)
                implementation=self.IMPLEMENTATION,
            )
            if self.strings
            else None
        )

    def _matches(self, text: str) -> list[tuple[int, int, int]]:
        """Every place a secret is in `text`, overlapping ones included, by where each ends."""
        return self._automaton.find_matches_as_indexes(text, overlapping=True) if self._automaton is not None else []

    def found(self, text: str) -> set[str]:
        """The secrets `text` contains."""
        return {self.strings[index] for index, _, _ in self._matches(text)}

    def mask(self, text: str, replacement: str) -> str:
        """`text` with every secret it contains replaced: secrets that overlap are one span, so no part of either
        shows."""
        spans: list[list[int]] = []
        for start, end in sorted((start, end) for _, start, end in self._matches(text)):
            if spans and start < spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], end)
            else:
                spans.append([start, end])
        out, last = [], 0
        for start, end in spans:
            out += [text[last:start], replacement]
            last = end
        return "".join(out) + text[last:] if out else text


def masked(value: Any, matcher: Matcher, replacement: str) -> Any:
    """`value` with every secret in its strings and keys replaced, at any depth."""
    if not matcher.strings:
        return value
    if isinstance(value, str):
        return matcher.mask(value, replacement)
    if isinstance(value, dict):
        return {matcher.mask(k, replacement): masked(v, matcher, replacement) for k, v in value.items()}
    if isinstance(value, list):
        return [masked(v, matcher, replacement) for v in value]
    return value
