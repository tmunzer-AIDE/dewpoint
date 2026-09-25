# SPDX-License-Identifier: Apache-2.0
"""Control node types the engine executes itself. Only the `flow` plugin may declare kind=control."""

IF = "flow.if@1"
SWITCH = "flow.switch@1"
LOOP = "flow.loop@1"
FILTER = "flow.filter@1"
SET_VARIABLES = "flow.set_variables@1"
DELAY = "flow.delay@1"
WAIT_UNTIL = "flow.wait_until@1"
STOP = "flow.stop@1"
FAIL = "flow.fail@1"
RUN_WORKFLOW = "flow.run_workflow@1"
TRANSFORM = "flow.transform@1"

CONTROL_TYPES = frozenset(
    {IF, SWITCH, LOOP, FILTER, SET_VARIABLES, DELAY, WAIT_UNTIL, STOP, FAIL, RUN_WORKFLOW, TRANSFORM}
)
