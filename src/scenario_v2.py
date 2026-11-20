"""Versioned, timezone-aware benchmark input for the active scenario contract."""
from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator


def _iso_offset(value):
    if isinstance(value, datetime):
        return value  # internal typed copies; JSON inputs are always strings
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})", value):
        raise ValueError("expected ISO 8601 datetime with explicit timezone offset")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class V2Event(StrictModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    start: datetime
    end: datetime
    category: str = Field(min_length=1)
    importance: int = Field(ge=1, le=5)
    fixed: bool
    participants: list[str]
    description: str

    @field_validator("start", "end", mode="before")
    @classmethod
    def iso_format(cls, value):
        return _iso_offset(value)

    @field_validator("start", "end")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ISO 8601 timestamp requires timezone offset")
        return value

    @model_validator(mode="after")
    def chronology(self):
        if self.start >= self.end:
            raise ValueError("event start must precede end")
        if len(self.participants) != len(set(self.participants)) or any(not p.strip() for p in self.participants):
            raise ValueError("participants must be unique, nonempty strings")
        return self


class V2Calendar(StrictModel):
    events: list[V2Event]

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [event.id for event in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate event id")
        return self


class V2HardConstraint(StrictModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    rule_type: Literal["protect_events_by_category", "protect_events_by_id", "daily_time_window"]
    event_categories: list[str] | None = None
    event_ids: list[str] | None = None
    start: time | None = None
    end: time | None = None

    @model_validator(mode="after")
    def rule_fields(self):
        if self.rule_type == "protect_events_by_category" and not self.event_categories:
            raise ValueError("protect_events_by_category requires event_categories")
        if self.rule_type == "protect_events_by_id" and not self.event_ids:
            raise ValueError("protect_events_by_id requires event_ids")
        if self.rule_type == "daily_time_window" and (self.start is None or self.end is None or self.start >= self.end):
            raise ValueError("daily_time_window requires start < end")
        if any(not x.strip() for x in (self.event_categories or []) + (self.event_ids or [])):
            raise ValueError("empty rule reference")
        if self.rule_type == "protect_events_by_category" and (self.event_ids or self.start or self.end):
            raise ValueError("unexpected fields for category protection")
        if self.rule_type == "protect_events_by_id" and (self.event_categories or self.start or self.end):
            raise ValueError("unexpected fields for event-id protection")
        if self.rule_type == "daily_time_window" and (self.event_categories or self.event_ids):
            raise ValueError("unexpected references for daily time window")
        if any(t is not None and t.tzinfo is not None for t in (self.start, self.end)):
            raise ValueError("daily local time must not carry a timezone offset")
        return self


class DurationRequirement(StrictModel):
    """Versioned sidecar rule; it does not change the shared scenario 2.0 JSON."""
    id: str = Field(min_length=1)
    kind: Literal["minimum_duration"]
    event_category: str = Field(min_length=1)
    start: datetime
    end: datetime
    minimum_minutes: int = Field(gt=0)
    complete_horizon: bool

    @field_validator("start", "end", mode="before")
    @classmethod
    def iso_format(cls, value):
        return _iso_offset(value)

    @model_validator(mode="after")
    def valid_window(self):
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("aggregate window requires aware start < end")
        return self


class AggregateSidecar(StrictModel):
    schema_version: Literal["1.0"]
    scenario_id: str
    scenario_sha256_canonical: str
    requirements: list[DurationRequirement] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_rules(self):
        ids = [item.id for item in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate aggregate requirement id")
        return self


class ConfirmedEventChange(StrictModel):
    """One externally confirmed exception for an existing protected event."""
    event_id: str = Field(min_length=1)
    type: Literal["move", "delete"]
    to_start: datetime | None = None
    to_end: datetime | None = None

    @field_validator("to_start", "to_end", mode="before")
    @classmethod
    def iso_format(cls, value):
        return None if value is None else _iso_offset(value)

    @model_validator(mode="after")
    def valid_target(self):
        if self.type == "move" and (self.to_start is None or self.to_end is None or self.to_start >= self.to_end):
            raise ValueError("confirmed move requires aware start < end")
        if self.type == "delete" and (self.to_start is not None or self.to_end is not None):
            raise ValueError("confirmed delete has no target time")
        return self


class ConfirmedChangesSidecar(StrictModel):
    schema_version: Literal["1.0"]
    scenario_id: str
    scenario_sha256_canonical: str
    changes: list[ConfirmedEventChange] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_changes(self):
        ids = [item.event_id for item in self.changes]
        if len(ids) != len(set(ids)):
            raise ValueError("one confirmed exception per event")
        return self


class V2SoftPreference(StrictModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    weight: int = Field(ge=1, le=5)


class V2AutonomyPreferences(StrictModel):
    allow_create_in_free_slots: bool
    allow_move_personal_flexible_events: bool
    require_confirmation_for_third_party_changes: bool
    require_confirmation_for_health_appointments: bool
    require_confirmation_for_high_impact_changes: bool
    notes: str = ""


class V2Profile(StrictModel):
    profile_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    timezone: str
    priorities: dict[str, int]
    hard_constraints: list[V2HardConstraint]
    soft_preferences: list[V2SoftPreference]
    autonomy_preferences: V2AutonomyPreferences

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("unknown IANA timezone") from None
        return value

    @field_validator("priorities")
    @classmethod
    def valid_priorities(cls, value: dict[str, int]) -> dict[str, int]:
        if any(not key.strip() or isinstance(weight, bool) or not 1 <= weight <= 5
               for key, weight in value.items()):
            raise ValueError("priorities require nonempty names and weights 1..5")
        return value

    @model_validator(mode="after")
    def unique_rules(self):
        ids = [x.id for x in self.hard_constraints] + [x.id for x in self.soft_preferences]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate constraint/preference id")
        return self


class V2Scenario(StrictModel):
    _aggregate_requirements: list[DurationRequirement] = PrivateAttr(default_factory=list)
    _confirmed_changes: list[ConfirmedEventChange] = PrivateAttr(default_factory=list)
    schema_version: Literal["2.0"]
    scenario_id: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    profile: V2Profile
    now: datetime
    calendar: V2Calendar
    user_request: str = Field(min_length=1)

    @property
    def aggregate_requirements(self) -> list[DurationRequirement]:
        return self._aggregate_requirements

    @property
    def confirmed_changes(self) -> list[ConfirmedEventChange]:
        return self._confirmed_changes

    @field_validator("now", mode="before")
    @classmethod
    def iso_now(cls, value):
        return _iso_offset(value)

    @field_validator("scenario_id", "family_id")
    @classmethod
    def safe_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
            raise ValueError("identifier must be filename-safe")
        return value

    @field_validator("now")
    @classmethod
    def aware_now(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("now requires timezone offset")
        return value

    @model_validator(mode="after")
    def references_and_offsets(self):
        ids = {event.id for event in self.calendar.events}
        for rule in self.profile.hard_constraints:
            if rule.rule_type == "protect_events_by_id" and not set(rule.event_ids or []) <= ids:
                raise ValueError(f"unknown event reference in constraint {rule.id}")
        zone = ZoneInfo(self.profile.timezone)
        for label, moment in [("now", self.now)] + [(f"{event.id}.{field}", getattr(event, field))
                                                     for event in self.calendar.events for field in ("start", "end")]:
            if moment.utcoffset() != moment.astimezone(zone).utcoffset():
                raise ValueError(f"timezone offset disagrees with profile timezone: {label}")
        return self


def confirmed_changes_fingerprint(scenario: V2Scenario) -> str | None:
    if not scenario.confirmed_changes:
        return None
    payload = [item.model_dump(mode="json") for item in scenario.confirmed_changes]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def load_scenario(path: Path) -> V2Scenario:
    scenario = V2Scenario.model_validate_json(path.read_text(encoding="utf-8"))
    canonical = json.dumps(scenario.model_dump(mode="json"), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    scenario_hash = hashlib.sha256(canonical).hexdigest()
    for base in (path.parent.parent, path.parent.parent.parent):
        sidecar_path = base / "aggregate_requirements" / f"{scenario.scenario_id}.json"
        if not sidecar_path.exists():
            continue
        sidecar = AggregateSidecar.model_validate_json(sidecar_path.read_text(encoding="utf-8"))
        if sidecar.scenario_id != scenario.scenario_id or sidecar.scenario_sha256_canonical != scenario_hash:
            raise ValueError("aggregate sidecar does not match scenario content")
        zone = ZoneInfo(scenario.profile.timezone)
        if any(moment.utcoffset() != moment.astimezone(zone).utcoffset()
               for rule in sidecar.requirements for moment in (rule.start, rule.end)):
            raise ValueError("aggregate window timezone differs from profile")
        scenario._aggregate_requirements = sidecar.requirements
        break
    for base in (path.parent.parent, path.parent.parent.parent):
        sidecar_path = base / "confirmed_changes" / f"{scenario.scenario_id}.json"
        if not sidecar_path.exists():
            continue
        sidecar = ConfirmedChangesSidecar.model_validate_json(sidecar_path.read_text(encoding="utf-8"))
        if sidecar.scenario_id != scenario.scenario_id or sidecar.scenario_sha256_canonical != scenario_hash:
            raise ValueError("confirmed-change sidecar does not match scenario content")
        ids = {event.id for event in scenario.calendar.events}
        zone = ZoneInfo(scenario.profile.timezone)
        if any(change.event_id not in ids for change in sidecar.changes):
            raise ValueError("confirmed-change sidecar references an unknown event")
        if any(moment.utcoffset() != moment.astimezone(zone).utcoffset()
               for change in sidecar.changes for moment in (change.to_start, change.to_end) if moment is not None):
            raise ValueError("confirmed-change target timezone differs from profile")
        scenario._confirmed_changes = sidecar.changes
        break
    return scenario


def load_manifest(root: Path) -> list[dict]:
    path = root / "data" / "benchmark_manifest.json"
    if not path.exists():
        if list((root / "data" / "scenarios").glob("*.json")):
            raise ValueError("scenarios exist without a manifest")
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "2.0":
        raise ValueError("v2 manifest schema_version must be 2.0")
    rows = document["scenarios"]
    if not isinstance(rows, list):
        raise ValueError("v2 manifest scenarios must be a list")
    ids, families, profiles = set(), {}, {}
    for row in rows:
        sid, family, split = row["scenario_id"], row["family_id"], row["split"]
        if sid in ids or split not in ("train", "dev", "test") or (family in families and families[family] != split):
            raise ValueError("duplicate scenario or family split leakage in v2 manifest")
        ids.add(sid)
        families[family] = split
        scenario = load_scenario(root / "data" / "scenarios" / f"{sid}.json")
        if scenario.scenario_id != sid or scenario.family_id != family or scenario.profile.profile_id != row["profile_id"]:
            raise ValueError(f"v2 manifest mismatch: {sid}")
        serialized_profile = scenario.profile.model_dump(mode="json")
        if row["profile_id"] in profiles and profiles[row["profile_id"]] != serialized_profile:
            raise ValueError(f"profile_id reused with different contents: {row['profile_id']}")
        profiles[row["profile_id"]] = serialized_profile
    files = {item.stem for item in (root / "data" / "scenarios").glob("*.json")}
    if files != ids:
        raise ValueError("v2 scenario files and manifest IDs differ")
    return rows
