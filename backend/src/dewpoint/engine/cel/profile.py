# SPDX-License-Identifier: Apache-2.0
"""The CEL profile (spec §5.1): runtime pin / function library / classifier rules. Changing any part is a new
profile, shipped only after the §5.9 gates pass for it."""

RUNTIME_DISTRIBUTION = "cel-expr-python"
RUNTIME_VERSION = "0.1.3"
FUNCTION_LIBRARY = "fn-1"
# cls-1 is the classifier as plan 2a-2 first ships it. Its rules changed while 2a-2 was built (caps, retained
# accumulators, work charges, regex eligibility) without a new version: no published version had classified an
# expression under it, because 2a-1 refused CEL at publish (cel.unavailable) and nothing had been released. Once 2a-2
# is merged, any change to the caps, the estimator or the classifier's limits is cls-2.
CLASSIFIER = "cls-1"
CURRENT_CEL_PROFILE = f"cel-cpp-{RUNTIME_VERSION}/{FUNCTION_LIBRARY}/{CLASSIFIER}"

# The one profile this worker build evaluates in-process, or None (spec §5.9 rollout). A build constant, never a
# setting: it is part of engine_abi, so changing it requires bumping ENGINE_ABI (tests/engine/cel/test_profile.py).
# Stays None until gates 1-7 pass, including the workflow-task gates that 2a-3 adds.
LOCAL_CEL_PROFILE: str | None = None


def profile_of(runtime_version: str) -> str:
    return f"cel-cpp-{runtime_version}/{FUNCTION_LIBRARY}/{CLASSIFIER}"
