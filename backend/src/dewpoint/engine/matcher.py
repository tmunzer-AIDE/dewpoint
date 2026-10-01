# SPDX-License-Identifier: Apache-2.0
"""Finding a run's secrets in text (engine 2b spec §3.5, §3.7): one Aho–Corasick automaton built once for a set of
strings, so a scan costs the text's length, never its length times the number of secrets. A secret has at least
MIN_SECRET characters: shorter ones would match ordinary text everywhere."""

from collections.abc import Iterable

import ahocorasick_rs

from dewpoint.engine.sensitive import MIN_SECRET


class Matcher:
    def __init__(self, strings: Iterable[str]) -> None:
        self.strings = tuple(sorted({s for s in strings if len(s) >= MIN_SECRET}))
        self._automaton = (
            ahocorasick_rs.AhoCorasick(list(self.strings), matchkind=ahocorasick_rs.MatchKind.LeftmostLongest)
            if self.strings
            else None
        )

    def _matches(self, text: str) -> list[tuple[int, int, int]]:
        return self._automaton.find_matches_as_indexes(text) if self._automaton is not None else []

    def found(self, text: str) -> set[str]:
        """The secrets `text` contains, the longest at each place."""
        return {self.strings[index] for index, _, _ in self._matches(text)}

    def mask(self, text: str, replacement: str) -> str:
        """`text` with every secret it contains replaced, the longest at each place."""
        out, last = [], 0
        for _, start, end in self._matches(text):
            out += [text[last:start], replacement]
            last = end
        return "".join(out) + text[last:] if out else text
