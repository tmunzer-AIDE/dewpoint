# 2b-1b §5.3 probe (throwaway)

The harness for the engine 2b spec's §5.3 go/no-go (§11.3): it runs the prototype on Temporal and checks, at every
continue, each component of the continued input against its computed maximum, and measures each workflow
activation's CPU and wall time. `.github/workflows/probe-2b1b.yml` runs it on the CI runner when this branch is
pushed. Never merged.

    PYTHONPATH=.:probe uv run python probe/cpu_bench.py 5
    DEV=1 WFT_SLOTS=2 CONCURRENT=4 PYTHONPATH=.:probe uv run python probe/probe_bound.py many_siblings
