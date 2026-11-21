from __future__ import annotations

import io
import tarfile
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


def test_get_file_names_parses_files_found(fixtures_dir: Path):
    """Live SARA firmware uses repeated <FilesFound> elements."""
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
    assert "sara20449_1970-01-01T01_00_00Z-5min.n42" in names
    assert "other_5min_backup.n42" in names
    assert "ignore_1h_spectrum.n42" in names


def test_get_file_names_parses_filename_tag_fallback(fixtures_dir: Path):
    xml = (fixtures_dir / "get_file_names_response_filename_tag.xml").read_bytes()
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


def test_download_files_extracts_tgz(fixtures_dir: Path, tmp_path: Path):
    """Live SARA returns /tmp/n42Files.tgz with full spectra/ paths inside."""
    soap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
                    xmlns:sara="http://www.technidata.com/ENVINET/SARA">
  <SOAP-ENV:Body>
    <sara:DownloadFilesResponse>
      <sara:DownloadPackage>/tmp/n42Files.tgz</sara:DownloadPackage>
    </sara:DownloadFilesResponse>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>
"""
    n42 = (fixtures_dir / "sample_5min.n42").read_bytes()
    wanted = "sara20449_1970-01-01T01_00_00Z-5min.n42"
    other = "sara20449_1970-01-01T00_55_00Z-5min.n42"

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in (
            (f"home/httpd/html/spectra/{wanted}", n42),
            (f"home/httpd/html/spectra/{other}", b"other"),
        ):
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    tgz_bytes = buf.getvalue()

    session = MagicMock()
    soap_resp = MagicMock()
    soap_resp.status_code = 200
    soap_resp.content = soap_xml
    get_resp = MagicMock()
    get_resp.status_code = 200
    get_resp.headers = {"Content-Type": "application/x-tgz"}
    get_resp.content = tgz_bytes
    session.post.return_value = soap_resp
    session.get.return_value = get_resp

    client = SaraSoapClient(
        InstrumentConfig(name="t", host="192.168.4.136"),
        session=session,
    )
    dest = tmp_path / "out"
    saved = client.download_files([wanted, other], dest)
    assert {p.name for p in saved} == {wanted, other}
    assert (dest / wanted).read_bytes() == n42
