from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

from sara_n42.config import InstrumentConfig
from sara_n42.soap_client import SaraSoapClient, resolve_download_package_url


def test_resolve_download_package_url():
    base = "http://192.168.4.136:80"
    assert resolve_download_package_url(base, "/tmp/x.zip").endswith(
        "/root/tmp/x.zip"
    )
    assert resolve_download_package_url(base, "/spectra/pkg.zip").endswith(
        "/spectra/pkg.zip"
    )


def test_get_file_names_parses_namespaced_response(fixtures_dir: Path):
    xml = (fixtures_dir / "get_file_names_response.xml").read_bytes()
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.content = xml
    session.post.return_value = resp

    client = SaraSoapClient(
        InstrumentConfig(name="t", host="192.168.4.136"),
        session=session,
    )
    names = client.get_file_names()
    assert "SARA_20261120_120000_5min.n42" in names
    assert "other_5min_backup.n42" in names
    assert "ignore_1h_spectrum.n42" in names


def test_download_files_extracts_zip(fixtures_dir: Path, tmp_path: Path):
    soap_xml = (fixtures_dir / "download_files_response.xml").read_bytes()
    n42 = (fixtures_dir / "sample_5min.n42").read_bytes()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SARA_20261120_120000_5min.n42", n42)
        zf.writestr("ignore_1h_spectrum.n42", b"nope")
    zip_bytes = buf.getvalue()

    session = MagicMock()

    soap_resp = MagicMock()
    soap_resp.status_code = 200
    soap_resp.content = soap_xml

    get_resp = MagicMock()
    get_resp.status_code = 200
    get_resp.headers = {"Content-Type": "application/zip"}
    get_resp.content = zip_bytes

    session.post.return_value = soap_resp
    session.get.return_value = get_resp

    client = SaraSoapClient(
        InstrumentConfig(name="t", host="192.168.4.136"),
        session=session,
    )
    dest = tmp_path / "out"
    saved = client.download_files(["SARA_20261120_120000_5min.n42"], dest)
    assert len(saved) == 1
    assert saved[0].name == "SARA_20261120_120000_5min.n42"
    assert saved[0].read_bytes() == n42
    # no overwrite
    saved2 = client.download_files(["SARA_20261120_120000_5min.n42"], dest)
    assert saved2 == []
