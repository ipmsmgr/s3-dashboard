"""Data structures for the Domain Feed Health Dashboard.

Version 2 extends the V1 dataclasses with real-data fields (device metadata,
op-window, file counts) while keeping full backward compatibility with the
simulated data path.  The ``RouterAccessPoint`` alias is preserved so existing
UI code compiles without changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Status = Literal["green", "yellow", "red"]


# ── Device (replaces RouterAccessPoint for real data) ──────────────────────

@dataclass(frozen=True)
class DeviceRecord:
    """One aimpoint (the device's config) read from its S3 aimpoint JSON.

    The full aimpoint structure (see ``aimpoint_structure.txt``) is kept as raw
    JSON in ``aimpoint_json`` and rendered field-by-field in the device panel,
    so the complete/evolving structure is captured without hand-mapping every
    key. ``op_window_*`` are derived from ``hours.hrs`` for the expected-file
    math; ``health_status`` and the ``files_*`` metrics carry the device's
    status (not part of the aimpoint). Stored as a JSON string (not a dict) so
    the dataclass stays hashable.
    """

    device_id: str                              # deviceID
    aimpoint_json: str = ""                     # full raw aimpoint JSON
    # Derived / status / metrics (not aimpoint fields).
    health_status: Status = "yellow"
    op_window_start: str = "00:00"              # derived from hours.hrs
    op_window_end: str = "00:00"
    files_actual: int = 0
    files_expected: int = 0


# Backward-compatible alias used by the V1 UI code (grid_config, ui.py).
RouterAccessPoint = DeviceRecord


# ── Feed ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FeedRecord:
    """One feed entry, sourced from a JSON-lines feed log or simulated."""

    feed_id: str
    status: Status
    count: int
    location: str
    observed_time: str
    latitude: float
    longitude: float
    feed_type: str
    source_system: str
    details: str = ""
    device_status: Optional[Status] = None       # populated from device file
    delivered_path: str = ""                     # raw "delivered" S3 key
    folder: str = ""                             # fe/fi/fo/fum (parts[:-4])
    # V1 compatibility: routers field kept so existing UI code compiles.
    routers: tuple[DeviceRecord, ...] = field(default_factory=tuple)


# ── Domain ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DomainRecord:
    """One domain with N feeds.

    ``domain_id`` is the stable identifier used for AgGrid row selection and
    database FK relationships.  ``folder`` is the aggregation key extracted
    from the ``delivered`` path (``fe/fi/fo/fum``).
    """

    domain_name: str
    feeds: tuple[FeedRecord, ...]
    last_observed_time: str
    domain_id: str = ""
    folder: str = ""


# ── In-memory tally structures (live view, not persisted until midnight) ───

@dataclass
class DeviceTally:
    """Running state for one device (aimpoint) within the current UTC day."""

    device_id: str
    aimpoint_json: str = ""
    health_status: str = "yellow"
    op_window_start: str = "00:00"
    op_window_end: str = "00:00"          # 00:00→00:00 = full 24h day (96 files)
    files_actual: int = 0
    files_expected: int = 0

    def to_device_record(self) -> DeviceRecord:
        return DeviceRecord(
            device_id=self.device_id,
            aimpoint_json=self.aimpoint_json,
            health_status=self.health_status,  # type: ignore[arg-type]
            op_window_start=self.op_window_start,
            op_window_end=self.op_window_end,
            files_actual=self.files_actual,
            files_expected=self.files_expected,
        )


@dataclass
class FeedTally:
    """Running state for one feed within the current UTC day."""

    feed_id: str
    device_id: str
    domain_id: str
    status: str = "yellow"
    device_status: str = "yellow"
    count: int = 0
    location: str = ""
    observed_time: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    feed_type: str = ""
    source_system: str = ""
    delivered_path: str = ""
    folder: str = ""


@dataclass
class DomainTally:
    """Running state for one domain within the current UTC day."""

    domain_id: str
    domain_name: str
    folder: str
    feeds: dict[str, FeedTally] = field(default_factory=dict)
    devices: dict[str, DeviceTally] = field(default_factory=dict)
    last_observed_time: str = ""

    def total_files_actual(self) -> int:
        return sum(d.files_actual for d in self.devices.values())

    def total_files_expected(self) -> int:
        return sum(d.files_expected for d in self.devices.values())


@dataclass
class DomainSetTally:
    """The complete in-memory tally for the current UTC day."""

    set_date: str                                          # "YYYY-MM-DD"
    domains: dict[str, DomainTally] = field(default_factory=dict)

    def get_or_create_domain(self, domain_id: str, domain_name: str, folder: str) -> DomainTally:
        if domain_id not in self.domains:
            self.domains[domain_id] = DomainTally(
                domain_id=domain_id,
                domain_name=domain_name,
                folder=folder,
            )
        return self.domains[domain_id]

    def to_domain_records(self) -> tuple[DomainRecord, ...]:
        """Convert the live tally to :class:`DomainRecord` tuples for the dashboard."""
        records: list[DomainRecord] = []
        for dt in self.domains.values():
            feeds: list[FeedRecord] = []
            for ft in dt.feeds.values():
                dev = dt.devices.get(ft.device_id)
                feeds.append(FeedRecord(
                    feed_id=ft.feed_id,
                    status=ft.status,           # type: ignore[arg-type]
                    device_status=ft.device_status,  # type: ignore[arg-type]
                    count=ft.count,
                    location=ft.location,
                    observed_time=ft.observed_time,
                    latitude=ft.latitude,
                    longitude=ft.longitude,
                    feed_type=ft.feed_type,
                    source_system=ft.source_system,
                    delivered_path=ft.delivered_path,
                    folder=ft.folder,
                    routers=(dev.to_device_record(),) if dev else (),
                ))
            records.append(DomainRecord(
                domain_name=dt.domain_name,
                feeds=tuple(feeds),
                last_observed_time=dt.last_observed_time,
                domain_id=dt.domain_id,
                folder=dt.folder,
            ))
        return tuple(records)
