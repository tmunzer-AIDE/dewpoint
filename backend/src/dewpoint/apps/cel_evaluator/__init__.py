# SPDX-License-Identifier: Apache-2.0
"""The isolated CEL evaluator (spec §5.7): a secretless, egress-free service that evaluates activity-class CEL.

It imports only the standard library and `dewpoint.engine.cel` (an import-linter contract and a test enforce this),
so its image holds the runtime, the function library, the classifier and the IPC server, and nothing else."""
