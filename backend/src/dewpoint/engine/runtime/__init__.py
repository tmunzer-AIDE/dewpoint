# SPDX-License-Identifier: Apache-2.0
"""`RunGraph`'s deterministic core (spec §6): a compiled version, the scheduler, value resolution and the control
nodes. It runs inside Temporal's sandbox: no I/O, no wall clock, no randomness."""
