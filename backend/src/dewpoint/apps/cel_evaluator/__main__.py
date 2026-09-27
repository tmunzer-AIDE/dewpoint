# SPDX-License-Identifier: Apache-2.0
"""`python -m dewpoint.apps.cel_evaluator [--health]`: start the evaluator, or check a running one."""

import argparse
import asyncio
import importlib.metadata
import os
import sys
import threading

from dewpoint.apps.cel_evaluator import capacity, config, server
from dewpoint.engine.cel import ipc, profile, runtime


def identity() -> str:
    """The profile this installation serves, from the installed runtime distribution (spec §5.7)."""
    return profile.profile_of(importlib.metadata.version(profile.RUNTIME_DISTRIBUTION))


async def _health(socket_path: str, expected: str) -> int:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(socket_path), 5)
        writer.write(ipc.encode(ipc.IdentityRequest().to_json()))
        await writer.drain()
        response = await asyncio.wait_for(ipc.read_frame(reader, ipc.MAX_RESPONSE), 5)
        writer.close()
    except (OSError, TimeoutError, asyncio.IncompleteReadError, ipc.FrameError):
        return 1
    return 0 if response.get("profile") == expected else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dewpoint-cel-evaluator")
    parser.add_argument("--health", action="store_true", help="exit 0 when the local evaluator answers")
    args = parser.parse_args(argv)
    try:
        cfg = config.load(os.environ)
        served = identity()
        if cfg.expected_profile is not None and cfg.expected_profile != served:
            raise config.StartupError(f"this image serves {served}, not {cfg.expected_profile}")
        if args.health:
            return asyncio.run(_health(cfg.socket, served))
        if sys.platform != "linux":
            raise config.StartupError("the evaluator needs Linux: it relies on rlimits and cgroup v2")
        cap = capacity.derive(cfg.cgroup, os.cpu_count() or 1, cfg.max_slots)
        runtime.compile_checked("1 + 1", {})  # load the runtime once, before any fork
        if threading.active_count() != 1:
            raise config.StartupError("the zygote must be single-threaded before it forks")
    except config.StartupError as e:
        print(f"cel-evaluator: {e}", file=sys.stderr)
        return 2
    print(f"cel-evaluator: serving {served} on {cfg.socket} with {cap.slots} slots", file=sys.stderr)
    asyncio.run(server.serve(cfg.socket, server.Evaluator(served, cap.slots)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
