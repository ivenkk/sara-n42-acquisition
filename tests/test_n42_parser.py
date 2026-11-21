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


def test_measurement_time_from_filename():
    dt = measurement_time_from_filename("SARA_20261120_120000_5min.n42")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 11
    assert dt.day == 20
    assert dt.hour == 12
