"""Layer 3 (provisional): Flyte-native tuning.

Exposes the tuning pipeline as composable Flyte tasks and TaskEnvironments so users
can compose it into their own workflows, run it on a schedule, or change
durability/caching behavior. Importing this module requires ``flyte`` (an optional
extra). Marked provisional until v1.0.

Layered stability contract: Layers 0-1 never import this module; the cluster/devbox
backend imports it lazily.
"""

from __future__ import annotations

from typing import Any


def _require_flyte():
    try:
        import flyte  # noqa: F401
    except ImportError as e:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "the Flyte backend needs the `flyte` SDK: `pip install harness-lock[flyte]`; "
            "fall back to --backend local otherwise"
        ) from e
    return __import__("flyte")


def envs():
    """Return the standard TaskEnvironments (core, trial, grade, train, serve)."""
    import flyte

    core = flyte.TaskEnvironment(name="harness_lock_core")
    trial = flyte.TaskEnvironment(
        name="al_trial",
        image=flyte.Image.from_debian_base(python_version=(3, 12)).with_pip_packages(
            "harness-lock", "pydantic", "python-frontmatter", "PyYAML",
        ),
    )
    return {
        "core": core,
        "trial": trial,
        "grade": trial,
    }


def build_pipeline():
    """Return the tuning pipeline as a single entrypoint task (in-process stage calls).

    Each stage mirrors §8.3 and is individually importable; ``run`` is the driver.
    """
    import flyte

    env = flyte.TaskEnvironment(name="al_lockpipeline")

    @env.task(cache="auto")
    async def lock_pipeline(manifest_path: str, backend: str = "local") -> dict[str, Any]:
        from hlock.api import lock

        lf = lock(manifest_path, backend=backend)
        return lf.to_dict()

    return {"run": lock_pipeline, "env": env}


def run_search(tuner, candidates, backend: Any) -> list[Any]:
    """Execute the search against the configured Flyte backend.

    Opens the Flyte config (``~/.flyte/config.yaml`` by default) and runs the
    ``lock_pipeline`` task. Trial-level fan-out is handled by Flyte on
    devbox/cluster; locally this function drives the in-process sweep.
    """
    if backend.target == "local":
        return _local_run(tuner, candidates)

    # devbox / cluster: require the SDK and delegate to the pipeline.
    import asyncio

    flyte = _require_flyte()
    cfg = backend.init_kwargs()
    asyncio.run(flyte.init(**cfg))
    pipeline = build_pipeline()
    run = pipeline["run"]
    asyncio.run(flyte.run(run, str(tuner.manifest.source_path or "harnesslock.toml"), "local"))
    # The pipeline wrote harness.lock; reconstruct TrialResults would require pulling a
    # remote artifact — for now report an empty sweep and let the driver read the lock.
    return []


def _local_run(tuner, candidates):

    results = []
    for c in candidates:
        r = tuner.run_trial(c.stack, c.task, c.seed, tuner.run_dir)
        results.append(r)
    return results
