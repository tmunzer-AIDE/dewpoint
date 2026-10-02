# SPDX-License-Identifier: Apache-2.0
import importlib.metadata

from dewpoint.engine import ENGINE_ABI
from dewpoint.engine.cel import profile


def test_the_profile_names_the_installed_runtime() -> None:
    assert importlib.metadata.version(profile.RUNTIME_DISTRIBUTION) == profile.RUNTIME_VERSION
    assert profile.CURRENT_CEL_PROFILE == profile.profile_of(profile.RUNTIME_VERSION) == "cel-cpp-0.1.3/fn-1/cls-1"


def test_local_evaluation_is_a_build_constant_tied_to_the_engine_abi() -> None:
    """Tripwire (spec §5.9 rollout): LOCAL_CEL_PROFILE is part of engine_abi. Changing it without bumping ENGINE_ABI
    would let an open run replay on a build that routes its CEL differently. Update both, then this pair."""
    assert (ENGINE_ABI, profile.LOCAL_CEL_PROFILE) == (6, profile.CURRENT_CEL_PROFILE)
