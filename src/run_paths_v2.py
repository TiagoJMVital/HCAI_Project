"""Canonical and legacy-compatible paths for schema-2 run artifacts."""
from __future__ import annotations

import json
from pathlib import Path


CONFIGURATIONS = {"A", "B", "C", "B_v2"}


def run_result_path(root: Path, scenario_id: str, run_id: str,
                    configuration: str, *, manifest_row: dict | None = None) -> Path:
    """Return the split/family/scenario path used by every new run."""
    if manifest_row is None:
        from final_dataset_v2 import combined_manifest
        manifest_row = next((row for row in combined_manifest(root)
                             if row["scenario_id"] == scenario_id), None)
    if manifest_row is None:
        raise ValueError(f"scenario is absent from all manifests: {scenario_id}")
    from final_dataset_v2 import run_prefix
    return (root / "eval" / "runs" / Path(*run_prefix(manifest_row)) /
            scenario_id / run_id / configuration / f"{scenario_id}.json")


def discover_result_paths(root: Path) -> list[Path]:
    """Find JSON results in both scenario-first and historical layouts."""
    runs_root = root / "eval" / "runs"
    if not runs_root.exists():
        return []
    return sorted(path for path in runs_root.rglob("*.json")
                  if path.parent.name in CONFIGURATIONS)


def path_identity(root: Path, path: Path, record: dict) -> tuple[str, str, str]:
    """Validate layout metadata and return scenario/run/config identity."""
    runs_root = root / "eval" / "runs"
    relative = path.relative_to(runs_root)
    parts = relative.parts
    scenario_id = record.get("scenario_id")
    run_id = record.get("run_id")
    configuration = record.get("configuration")
    if not all(isinstance(value, str) and value
               for value in (scenario_id, run_id, configuration)):
        raise ValueError(f"run identity is incomplete: {path}")
    if path.stem != scenario_id:
        raise ValueError(f"scenario ID/filename mismatch: {path}")
    if len(parts) == 3:  # <run_id>/<configuration>/<scenario_id>.json
        path_run_id, path_configuration, _ = parts
    elif len(parts) >= 4:  # prefixes / <scenario_id>/<run_id>/<configuration>/<scenario_id>.json
        path_scenario, path_run_id, path_configuration, _ = parts[-4:]
        if path_scenario != scenario_id:
            raise ValueError(f"scenario ID/path mismatch: {path}")
    else:
        raise ValueError(f"unsupported run result layout: {path}")
    if path_run_id != run_id:
        raise ValueError(f"run ID/path mismatch: {path}")
    # B_v2 is a readable historical directory name for configuration B.
    if path_configuration != configuration and not (
            path_configuration == "B_v2" and configuration == "B"):
        raise ValueError(f"configuration/path mismatch: {path}")
    return scenario_id, run_id, configuration


def resolve_run_reference(root: Path, reference: Path) -> Path:
    """Resolve a current path or an obsolete legacy result path after migration."""
    candidate = reference if reference.is_absolute() else root / reference
    if candidate.exists():
        return candidate
    try:
        relative = candidate.resolve().relative_to((root / "eval" / "runs").resolve())
    except ValueError:
        raise FileNotFoundError(reference)
    if len(relative.parts) == 3:
        run_id, configuration, filename = relative.parts
        canonical = (root / "eval" / "runs" / Path(filename).stem / run_id /
                     configuration / filename)
        if canonical.exists():
            return canonical
    matches = []
    for path in discover_result_paths(root):
        if path.name != relative.name:
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            _, discovered_run_id, _ = path_identity(root, path, record)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if len(relative.parts) >= 3 and discovered_run_id == relative.parts[-3]:
            matches.append(path)
    archive = root / "eval" / "historical_run_sources"
    if archive.exists():
        requested_run_id = relative.parts[-3] if len(relative.parts) >= 3 else None
        for path in archive.rglob(relative.name):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (record.get("run_id") == requested_run_id and
                    record.get("scenario_id") == Path(relative.name).stem):
                matches.append(path)
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError(reference)
