from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfoNotFoundError

from sara_n42 import n42_parser
from sara_n42.n42_parser import (
    _BEIJING_FIXED,
    _format_time,
    _resolve_display_tz,
    _to_beijing,
    measurement_time_from_filename,
    parse_n42,
)


def test_parse_n42_spectrum(fixtures_dir: Path):
    data = parse_n42(fixtures_dir / "sample_5min.n42")
    assert data.error is None
    assert data.measurement_time_source == "n42"
    # Fixture StartTime 2026-11-20T12:00:00 is naive → assumed UTC → Beijing +8
    assert data.measurement_time_display == "2026-11-20 20:00:00"
    assert len(data.counts) == 10
    assert data.x_unit == "keV"
    assert data.channels[1] == 1.5  # 0 + 1.5 * channel
    # CountDoseData/DoseRate (not nuclide sara:DoseRate)
    assert data.dose_rate == 9.550e-02
    assert data.dose_rate_unit == "uSv/h"
    assert data.dose_rate_display == "9.550e-02 uSv/h"


def test_parse_n42_dose_rate_missing(tmp_path: Path):
    path = tmp_path / "no_dose.n42"
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<N42InstrumentData xmlns="http://physics.nist.gov/N42/2011/N42">
  <Measurement>
    <Spectrum>
      <StartTime>2026-11-20T12:00:00</StartTime>
      <ChannelData>0 1 2</ChannelData>
    </Spectrum>
  </Measurement>
</N42InstrumentData>
""",
        encoding="utf-8",
    )
    data = parse_n42(path)
    assert data.error is None
    assert data.dose_rate is None
    assert data.dose_rate_unit is None
    assert data.dose_rate_display == "未知"


def test_parse_n42_dose_rate_normalized_scientific(tmp_path: Path):
    """Plain decimal DoseRate values are normalized to scientific display."""
    path = tmp_path / "decimal_dose.n42"
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<N42InstrumentData xmlns="http://physics.nist.gov/N42/2011/N42"
  xmlns:envinet="http://www.technidata.com/ENVINET">
  <Measurement>
    <Spectrum>
      <StartTime>2026-11-20T12:00:00Z</StartTime>
      <ChannelData>0 1 2</ChannelData>
    </Spectrum>
    <CountDoseData>
      <DoseRate Units="uSv" envinet:TimeRelation="h">0.0955</DoseRate>
    </CountDoseData>
  </Measurement>
</N42InstrumentData>
""",
        encoding="utf-8",
    )
    data = parse_n42(path)
    assert data.error is None
    assert data.dose_rate == 0.0955
    assert data.dose_rate_display == "9.550e-02 uSv/h"
    # Explicit UTC Z → same Beijing wall clock as naive-assumed-UTC fixture
    assert data.measurement_time_display == "2026-11-20 20:00:00"


def test_measurement_time_from_filename():
    dt = measurement_time_from_filename("SARA_20261120_120000_5min.n42")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 11
    assert dt.day == 20
    assert dt.hour == 12


def test_filename_measurement_time_display_beijing(tmp_path: Path):
    """Filename-only stamp (naive) is also shown in Beijing time."""
    path = tmp_path / "SARA_20261120_120000_5min.n42"
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<N42InstrumentData xmlns="http://physics.nist.gov/N42/2011/N42">
  <Measurement>
    <Spectrum>
      <ChannelData>1 2 3</ChannelData>
    </Spectrum>
  </Measurement>
</N42InstrumentData>
""",
        encoding="utf-8",
    )
    data = parse_n42(path)
    assert data.measurement_time_source == "filename"
    assert data.measurement_time_display == "2026-11-20 20:00:00"


def test_beijing_tz_falls_back_when_zoneinfo_unavailable():
    """Windows without tzdata/IANA DB: ZoneInfoNotFoundError → fixed UTC+8."""

    def _raise_missing(_key: str):
        raise ZoneInfoNotFoundError("No time zone found with key Asia/Shanghai")

    with patch.object(n42_parser, "ZoneInfo", side_effect=_raise_missing):
        tz = _resolve_display_tz()
    assert tz is _BEIJING_FIXED

    utc_noon = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    with patch.object(n42_parser, "_DISPLAY_TZ", _BEIJING_FIXED):
        assert _to_beijing(utc_noon).strftime("%Y-%m-%d %H:%M:%S") == "2026-11-20 20:00:00"
        assert _format_time(datetime(2026, 11, 20, 12, 0, 0)) == "2026-11-20 20:00:00"
