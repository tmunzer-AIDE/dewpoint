# SPDX-License-Identifier: Apache-2.0
"""The operator's recovery (the owner's rulings on the 2b-4b M3 design, rev 1 and 2): the commands an operator may ask
for, each acting only on an item with one of its reasons recorded, and the kinds of work a held item is held for."""

from typing import Literal, get_args

CommandKind = Literal[
    "record_lost_run",
    "record_lost_subrun",
    "release_lost_slot",
    "settle_ended",
    "inspect_unresolved_send",
    "abandon_start",
]
# A request left unresolved, ended by its operator (task 10): never its send. Its evidence is structured, canonical JSON
ABANDON = "abandon_start"
ABANDON_EVIDENCE_LIMIT = 4_000
# The reveal's own command (2b-4b M4 recovery, task 9): an unresolved send's identifiers, shown to its confirming
# operator's recovery login alone; it names a request, and no recovery reason
INSPECT = "inspect_unresolved_send"
# A held item's release, a command its operator confirms (2b-4b M4 recovery, task 8): bound to the holds it showed
RELEASES = ("release_held", "release_held_many")
WorkKind = Literal["dispatch", "reconcile_starting", "reconcile_open", "reconcile_slot", "cancel", "match", "subrun"]
# Each command, and the recorded reasons it acts on
COMMANDS: dict[CommandKind, tuple[str, ...]] = {
    "record_lost_run": ("run_history_missing",),
    "record_lost_subrun": ("subrun_history_missing",),
    "release_lost_slot": ("slot_history_missing",),
    "settle_ended": ("start_after_end", "start_history_missing"),
    "inspect_unresolved_send": (),
    "abandon_start": ("start_unresolved",),
}
# Acting on history Temporal no longer has: only with the operator's evidence of how the loss was confirmed
LOST = ("record_lost_run", "record_lost_subrun", "release_lost_slot")
EVIDENCE_LIMIT = 500
WORK: tuple[str, ...] = get_args(WorkKind)
RELEASE_MAX = 1_000  # held items one bulk release frees, at most (the owner's ruling on the M3 checkpoint)
AUDITED_IDS = 100  # a bulk release's audit entry names at most this many released items: 10 entries at most
