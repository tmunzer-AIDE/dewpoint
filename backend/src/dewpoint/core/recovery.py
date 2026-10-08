# SPDX-License-Identifier: Apache-2.0
"""The operator's recovery (the owner's rulings on the 2b-4b M3 design, rev 1 and 2): the commands an operator may ask
for, each acting only on an item with one of its reasons recorded, and the kinds of work a held item is held for."""

from typing import Literal, get_args

CommandKind = Literal["record_lost_run", "record_lost_subrun", "release_lost_slot", "settle_ended"]
WorkKind = Literal["dispatch", "reconcile_starting", "reconcile_open", "reconcile_slot", "cancel", "match", "subrun"]
# Each command, and the recorded reasons it acts on
COMMANDS: dict[CommandKind, tuple[str, ...]] = {
    "record_lost_run": ("run_history_missing",),
    "record_lost_subrun": ("subrun_history_missing",),
    "release_lost_slot": ("slot_history_missing",),
    "settle_ended": ("start_after_end", "start_history_missing"),
}
# Acting on history Temporal no longer has: only with the operator's evidence of how the loss was confirmed
LOST = ("record_lost_run", "record_lost_subrun", "release_lost_slot")
EVIDENCE_LIMIT = 500
WORK: tuple[str, ...] = get_args(WorkKind)
RELEASE_MAX = 1_000  # held items one bulk release frees, at most (the owner's ruling on the M3 checkpoint)
