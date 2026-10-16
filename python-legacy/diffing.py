"""Structural + evidence diff between the working lock and the committed one.

``hpm diff`` compares the current ``agent.lock`` (the result of the last ``hpm lock``)
against the git-committed version, and renders an evidence diff suitable for a PR
description.
"""

from __future__ import annotations

from pathlib import Path

from hpm.lockfile import Lockfile


class Diff:
    def __init__(self, path: str | Path = "agent.lock") -> None:
        self.path = Path(path)
        self.committed = self._read_committed()

    def _read_committed(self) -> Lockfile | None:
        try:
            import subprocess

            raw = subprocess.run(
                ["git", "show", f"HEAD:{self.path}"], capture_output=True, text=True, check=True
            ).stdout
            from hpm.lockfile import Lockfile as L

            obj = L.model_validate(
                __import__("tomllib").loads("\n".join(l for l in raw.splitlines() if not l.startswith("#")))
            )
            return obj
        except Exception:
            return None

    def run(self, fmt: str = "text") -> str:
        cur = Lockfile.load(self.path)
        if self.committed is None:
            return f"[diff] no committed agent.lock to diff against (HEAD:{self.path})"

        lines = []
        if self.committed.stack.get("name") != cur.stack.get("name"):
            lines.append(f"stack name    {self.committed.stack.get('name')} -> {cur.stack.get('name')}")
        old_model = self.committed.llms[0].model if self.committed.llms else "?"
        new_model = cur.llms[0].model if cur.llms else "?"
        if old_model != new_model:
            lines.append(f"llm.planner   {old_model} -> {new_model}")
        if self.committed.harness.name != cur.harness.name:
            lines.append(f"harness       {self.committed.harness.name} -> {cur.harness.name}")

        oe, ne = self.committed.evidence, cur.evidence
        old_sr = oe.success_rate.get("mean")
        new_sr = ne.success_rate.get("mean")
        if old_sr is not None and new_sr is not None:
            delta = new_sr - old_sr
            lines.append(f"success-rate  {old_sr:.2f} -> {new_sr:.2f} ({delta:+.2f})")
        oc, nc = oe.cost_usd_per_task.get("mean"), ne.cost_usd_per_task.get("mean")
        if oc is not None and nc is not None:
            pct = (nc - oc) / oc * 100 if oc else 0.0
            lines.append(f"cost/task     {oc:.3f} -> {nc:.3f} ({pct:+.0f}%)")
        lines.append(f"trials        {oe.trials} -> {ne.trials}")

        if not lines:
            return "[diff] no changes"
        if fmt == "md":
            return "\n".join(f"- {l}" for l in lines)
        return "\n".join(lines)
