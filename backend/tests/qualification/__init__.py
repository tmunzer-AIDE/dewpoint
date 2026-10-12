# SPDX-License-Identifier: Apache-2.0
"""A target's qualification procedures (2b-4b M4 recovery, task 18): each run by hand against one target, under its
own approval (`DEWPOINT_QUALIFICATION_APPROVED`), with test credentials only, its record written where it's told.
None runs in the suite: `test_guard.py` and `test_procedures.py` check their guard and their logic without a target.

    DEWPOINT_QUALIFICATION_APPROVED=<approval id> python -m tests.qualification.<procedure> --help

The deployment guide (docs/operations/deployment.md, "Operator recovery") says when each is run, and run again."""
