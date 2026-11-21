from __future__ import annotations

from pathlib import Path

from sara_n42.scheduler import AcquisitionScheduler
from sara_n42.soap_client import SaraSoapError


class FakeClient:
    def __init__(self, instrument, *, names=None, fail=False, payload=None):
        self.instrument = instrument
        self._names = names or []
        self._fail = fail
        self._payload = payload or {}

    def get_file_names(self, file_type: str = ".n42"):
        if self._fail:
            raise SaraSoapError("instrument down")
        return list(self._names)

    def download_files(self, filenames, dest_dir: Path):
        dest_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        for name in filenames:
            target = dest_dir / name
            if target.exists():
                continue
            target.write_bytes(self._payload.get(name, b"n42"))
            saved.append(target)
        return saved


def test_scheduler_isolates_instrument_failure(app_config, tmp_path: Path):
    calls = []

    def factory(inst):
        calls.append(inst.host)
        if inst.host.endswith(".137"):
            return FakeClient(inst, fail=True)
        return FakeClient(
            inst,
            names=[
                "keep_5min.n42",
                "skip_1h.n42",
            ],
        )

    sched = AcquisitionScheduler(app_config, client_factory=factory)
    sched.run_once()

    assert "192.168.4.136" in calls
    assert "192.168.4.137" in calls
    good = app_config.storage_root / "192.168.4.136" / "keep_5min.n42"
    assert good.is_file()
    assert not (app_config.storage_root / "192.168.4.136" / "skip_1h.n42").exists()
    assert "192.168.4.137" in sched.last_errors

    # second run: no overwrite / no re-download needed
    before = good.read_bytes()
    sched.run_once()
    assert good.read_bytes() == before


def test_scheduler_skips_existing(app_config):
    host = "192.168.4.136"
    dest = app_config.storage_root / host
    dest.mkdir(parents=True)
    existing = dest / "already_5min.n42"
    existing.write_bytes(b"old")

    def factory(inst):
        return FakeClient(inst, names=["already_5min.n42", "new_5min.n42"])

    sched = AcquisitionScheduler(app_config, client_factory=factory)
    sched.run_once()
    assert existing.read_bytes() == b"old"
    assert (dest / "new_5min.n42").is_file()
