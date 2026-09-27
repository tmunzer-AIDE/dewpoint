# SPDX-License-Identifier: Apache-2.0
"""Gate 3 (spec §5.9): one result across 8 processes with different PYTHONHASHSEED values. The C++ maps are seeded
per process too, so this is what catches iteration order leaking. Maps are also built in a different insertion
order in every process."""

import json
import os
import subprocess
import sys
import textwrap

CHILD = textwrap.dedent(
    """
    import json, random, sys
    from dewpoint.engine.cel import evaluate, runtime, types as T

    seed = int(sys.argv[1])
    keys = [f"k{i:02d}" for i in range(24)]
    random.Random(seed).shuffle(keys)
    m = {k: int(k[1:]) for k in keys}
    z = {"a": 0, "b": 5, "c": 7}
    corpus = [
        ("sortedKeys(m)", {"m": T.MAP}, {"m": m}),
        ("sortedKeys(m).map(k, m[k])", {"m": T.MAP}, {"m": m}),
        ("m", {"m": T.MAP}, {"m": m}),
        ("{'b': m.k01, 'a': m.k02}", {"m": T.MAP}, {"m": m}),
        ("sortedKeys(z).all(k, 10 / z[k] > 3)", {"z": T.MAP}, {"z": z}),
        ("sortedKeys(z).exists(k, 10 / z[k] > 3)", {"z": T.MAP}, {"z": z}),
        ("sortedKeys(z).exists_one(k, 10 / z[k] > 3)", {"z": T.MAP}, {"z": z}),
        ("string(0.1 + 0.2)", {}, {}),
        ("m == {'k00': 0} ? 1 : size(m)", {"m": T.MAP}, {"m": m}),
        ("'k03' in m", {"m": T.MAP}, {"m": m}),
        ("[macNormalize('5C:5B:35:00:00:01'), ipInCidr('10.1.2.3', '10.0.0.0/8')]", {}, {}),
    ]
    out = []
    for expr, decls, values in corpus:
        o = evaluate.run(evaluate.compiled(expr, decls), values)
        out.append(o.to_json())
    print(json.dumps(out, sort_keys=True))
    """
)


def test_results_are_identical_across_processes() -> None:
    outputs = set()
    for seed in range(8):
        env = {**os.environ, "PYTHONHASHSEED": str(seed * 7919 + 1)}
        done = subprocess.run(
            [sys.executable, "-c", CHILD, str(seed)], env=env, capture_output=True, text=True, check=True, timeout=120
        )
        outputs.add(done.stdout)
    assert len(outputs) == 1, outputs
    results = json.loads(outputs.pop())
    assert results[0] == {"ok": [f"k{i:02d}" for i in range(24)]}
    assert results[4] == {"ok": False}  # an error absorbed by a false: order doesn't matter
