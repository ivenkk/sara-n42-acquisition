from pathlib import Path

from sara_n42.n42_parser import measurement_time_from_filename, parse_n42


def test_parse_n42_spectrum(fixtures_dir: Path):
    data = parse_n42(fixtures_dir / "sample_5min.n42")
    assert data.error is None
    assert data.measurement_time_source == "n42"
    assert data.measurement_time_display.startswith("2026-11-20")
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


def test_measurement_time_from_filename():
    dt = measurement_time_from_filename("SARA_20261120_120000_5min.n42")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 11
    assert dt.day == 20
    assert dt.hour == 12
