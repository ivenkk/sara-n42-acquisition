"""Parse ANSI/IEEE N42.42 spectrum files for measurement time and counts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

# Common N42.42 local names (namespace-agnostic)
_START_TAGS = (
    "StartTime",
    "StartDateTime",
    "MeasurementStartDateTime",
    "ClassStartDateTime",
)
_CHANNEL_DATA_TAGS = ("ChannelData",)
_CAL_COEFF_TAGS = ("Coefficient",)
_ENERGY_CAL_PARENTS = ("EnergyCalibration", "Calibration")
_UNKNOWN = "未知"


@dataclass(frozen=True)
class SpectrumData:
    filename: str
    path: str
    measurement_time: datetime | None
    measurement_time_display: str
    measurement_time_source: str  # n42 | filename | unknown
    channels: list[float]
    counts: list[float]
    x_unit: str  # keV | channel
    x_label: str
    y_label: str = "计数 (counts)"
    dose_rate: float | None = None
    dose_rate_unit: str | None = None
    dose_rate_display: str = _UNKNOWN
    error: str | None = None


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    if ":" in tag:
        return tag.split(":", 1)[-1]
    return tag


def _parse_datetime(text: str) -> datetime | None:
    text = text.strip()
    if not text:
        return None
    # Normalize Zulu
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    candidates = [
        text,
        text.replace(" ", "T", 1),
    ]
    for cand in candidates:
        try:
            return datetime.fromisoformat(cand)
        except ValueError:
            pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y%m%d%H%M%S",
        "%Y%m%d_%H%M%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text[:26], fmt)
        except ValueError:
            continue
    return None


def measurement_time_from_filename(name: str) -> datetime | None:
    """
    Best-effort parse of common SARA-style timestamps embedded in filenames.
    Never uses filesystem mtime.
    """
    stem = Path(name).stem
    patterns = [
        r"(20\d{2})[_-]?(\d{2})[_-]?(\d{2})[_-]?(\d{2})[_-]?(\d{2})[_-]?(\d{2})",
        r"(20\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, stem)
        if not m:
            continue
        y, mo, d, h, mi, s = (int(x) for x in m.groups())
        try:
            return datetime(y, mo, d, h, mi, s)
        except ValueError:
            continue
    return None


def _channel_data_values(text: str) -> list[float]:
    text = text.strip()
    if not text:
        return []
    # N42 often uses space/newline separated integers; sometimes compressed runs.
    parts = re.split(r"[\s,;]+", text)
    values: list[float] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("["):
            # Skip compressed-data markers we cannot expand without full codec
            continue
        try:
            values.append(float(part))
        except ValueError:
            continue
    return values


def _energy_coefficients(root: ET.Element) -> list[float] | None:
    """Return polynomial energy calibration coefficients if present."""
    for el in root.iter():
        if _local(el.tag) not in _ENERGY_CAL_PARENTS and _local(el.tag) != "EnergyCalibration":
            continue
        coeffs: list[float] = []
        for child in el.iter():
            if _local(child.tag) in _CAL_COEFF_TAGS and child.text:
                try:
                    coeffs.append(float(child.text.strip()))
                except ValueError:
                    continue
        if coeffs:
            return coeffs
    # Fallback: any Coefficient under EnergyCalibration-like path already covered;
    # try top-level Coefficient list under Calibration.
    return None


def _apply_energy_cal(channels: list[float], coeffs: list[float]) -> list[float]:
    energies: list[float] = []
    for ch in channels:
        e = 0.0
        power = 1.0
        for c in coeffs:
            e += c * power
            power *= ch
        energies.append(e)
    return energies


def _format_time(dt: datetime | None) -> str:
    if dt is None:
        return _UNKNOWN
    if dt.tzinfo is not None:
        return dt.isoformat(sep=" ", timespec="seconds")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _attr_local(name: str) -> str:
    return _local(name)


def _dose_rate_unit(el: ET.Element) -> str | None:
    """Build unit string from Units + optional TimeRelation (e.g. uSv + h → uSv/h)."""
    units: str | None = None
    time_relation: str | None = None
    for key, value in el.attrib.items():
        local = _attr_local(key)
        if local == "Units" and value:
            units = value.strip()
        elif local == "TimeRelation" and value:
            time_relation = value.strip()
    if not units:
        return None
    if time_relation:
        return f"{units}/{time_relation}"
    return units


def _parse_dose_rate(root: ET.Element) -> tuple[float | None, str | None, str]:
    """
    Extract gross dose rate from CountDoseData/DoseRate (SARA N42).

    Live files use e.g. CountDoseData/DoseRate with Units="uSv"
    and TimeRelation="h" (value like 9.550e-02 → unit uSv/h).
    Nuclide-scoped sara:DoseRate values are ignored here.
    """
    for el in root.iter():
        if _local(el.tag) != "CountDoseData":
            continue
        for child in el:
            if _local(child.tag) != "DoseRate" or not child.text:
                continue
            text = child.text.strip()
            if not text:
                continue
            # Gross dose rate is a single number; skip multi-value lists.
            if re.search(r"[\s,;]", text):
                continue
            try:
                value = float(text)
            except ValueError:
                continue
            unit = _dose_rate_unit(child)
            if unit:
                display = f"{text} {unit}"
            else:
                display = text
            return value, unit, display
    return None, None, _UNKNOWN


def parse_n42(path: Path | str) -> SpectrumData:
    """
    Parse one .n42 file.

    Measurement time priority: N42 content → filename → unknown.
    Never uses HTTP Date or file download/mtime.
    """
    path = Path(path)
    filename = path.name
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except (ET.ParseError, OSError) as exc:
        return SpectrumData(
            filename=filename,
            path=str(path),
            measurement_time=None,
            measurement_time_display=_UNKNOWN,
            measurement_time_source="unknown",
            channels=[],
            counts=[],
            x_unit="channel",
            x_label="道址 (channel)",
            error=f"N42 解析失败: {exc}",
        )

    mt: datetime | None = None
    source = "unknown"
    for el in root.iter():
        if _local(el.tag) in _START_TAGS and el.text:
            mt = _parse_datetime(el.text)
            if mt is not None:
                source = "n42"
                break

    if mt is None:
        mt = measurement_time_from_filename(filename)
        if mt is not None:
            source = "filename"

    dose_rate, dose_rate_unit, dose_rate_display = _parse_dose_rate(root)

    counts: list[float] = []
    for el in root.iter():
        if _local(el.tag) in _CHANNEL_DATA_TAGS and el.text:
            counts = _channel_data_values(el.text)
            if counts:
                break

    if not counts:
        return SpectrumData(
            filename=filename,
            path=str(path),
            measurement_time=mt,
            measurement_time_display=_format_time(mt),
            measurement_time_source=source,
            channels=[],
            counts=[],
            x_unit="channel",
            x_label="道址 (channel)",
            dose_rate=dose_rate,
            dose_rate_unit=dose_rate_unit,
            dose_rate_display=dose_rate_display,
            error="未找到 ChannelData 能谱数据",
        )

    channels = [float(i) for i in range(len(counts))]
    coeffs = _energy_coefficients(root)
    if coeffs:
        x_values = _apply_energy_cal(channels, coeffs)
        x_unit = "keV"
        x_label = "能量 (keV)"
    else:
        x_values = channels
        x_unit = "channel"
        x_label = "道址 (channel)"

    return SpectrumData(
        filename=filename,
        path=str(path),
        measurement_time=mt,
        measurement_time_display=_format_time(mt),
        measurement_time_source=source,
        channels=x_values,
        counts=counts,
        x_unit=x_unit,
        x_label=x_label,
        dose_rate=dose_rate,
        dose_rate_unit=dose_rate_unit,
        dose_rate_display=dose_rate_display,
        error=None,
    )


def sort_key_measurement_time(path: Path) -> tuple:
    """Sort key: measurement time descending; unknown last."""
    data = parse_n42(path)
    if data.measurement_time is None:
        return (1, datetime.min, path.name)
    # naive vs aware: strip tz for ordering consistency
    mt = data.measurement_time
    if mt.tzinfo is not None:
        mt = mt.replace(tzinfo=None)
    return (0, mt, path.name)
