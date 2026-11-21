"""HTTP Digest + SOAP client for SARA Spectra Folder."""

from __future__ import annotations

import io
import logging
import re
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

import requests
from requests.auth import HTTPDigestAuth

from .config import InstrumentConfig

logger = logging.getLogger(__name__)

SOAP_PATH = "/SARA_Server.soap"
SPECTRA_DIRECTORY = "/home/httpd/html/spectra/"

SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
SARA_NS = "http://www.technidata.com/ENVINET/SARA"

NS = {
    "SOAP-ENV": SOAP_ENV_NS,
    "sara": SARA_NS,
}


class SaraSoapError(Exception):
    """Raised when a SOAP or download step fails for one instrument."""


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    if ":" in tag:
        return tag.split(":", 1)[-1]
    return tag


def _find_all_by_local(root: ET.Element, local_name: str) -> list[ET.Element]:
    return [el for el in root.iter() if _local(el.tag) == local_name]


def _find_text_by_local(root: ET.Element, local_name: str) -> str | None:
    for el in _find_all_by_local(root, local_name):
        if el.text and el.text.strip():
            return el.text.strip()
    return None


def _build_get_file_names_body(file_type: str = ".n42") -> str:
    return f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<SOAP-ENV:Envelope
  xmlns:SOAP-ENV="{SOAP_ENV_NS}"
  xmlns:sara="{SARA_NS}">
  <SOAP-ENV:Body>
    <sara:GetFileNames>
      <sara:Directory>{SPECTRA_DIRECTORY}</sara:Directory>
      <sara:FileType>{file_type}</sara:FileType>
    </sara:GetFileNames>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>
"""


def _build_download_files_body(filenames: Iterable[str]) -> str:
    items = "\n".join(
        f"      <sara:FileToDownload>{name}</sara:FileToDownload>" for name in filenames
    )
    return f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<SOAP-ENV:Envelope
  xmlns:SOAP-ENV="{SOAP_ENV_NS}"
  xmlns:sara="{SARA_NS}">
  <SOAP-ENV:Body>
    <sara:DownloadFiles>
      <sara:Directory>{SPECTRA_DIRECTORY}</sara:Directory>
{items}
    </sara:DownloadFiles>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>
"""


def resolve_download_package_url(base_url: str, package_path: str) -> str:
    """
    Map DownloadPackage path to an HTTP URL.

    Management-page JS prefixes the package path with ``../../../../root``
    relative to the site. We normalize common absolute filesystem paths to
    HTTP URLs under the instrument host.
    """
    raw = package_path.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw

    # Already a site-relative or root-relative web path
    if raw.startswith("/tmp/") or raw.startswith("/var/") or raw.startswith("/home/"):
        # Emulate ../../../../root + absolute FS path → /root/... on lighttpd
        # Observed pattern from spectra.js: prefix "../../../../root" then join.
        web_path = "/root" + raw
        return base_url.rstrip("/") + web_path

    if raw.startswith("/"):
        return base_url.rstrip("/") + raw

    # Relative package path as returned by some firmwares
    return base_url.rstrip("/") + "/" + raw.lstrip("./")


class SaraSoapClient:
    """Digest-authenticated SOAP client for one SARA instrument."""

    def __init__(
        self,
        instrument: InstrumentConfig,
        *,
        timeout: float = 20.0,
        session: requests.Session | None = None,
    ) -> None:
        self.instrument = instrument
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.auth = HTTPDigestAuth(instrument.username, instrument.password)
        self.soap_url = f"{instrument.base_url}{SOAP_PATH}"

    def _soap_post(self, body: str) -> ET.Element:
        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": '""',
        }
        try:
            resp = self.session.post(
                self.soap_url,
                data=body.encode("utf-8"),
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SaraSoapError(
                f"SOAP 请求失败 ({self.instrument.host}): {exc}"
            ) from exc

        if resp.status_code != 200:
            raise SaraSoapError(
                f"SOAP HTTP {resp.status_code} ({self.instrument.host}): "
                f"{resp.text[:200]}"
            )

        try:
            return ET.fromstring(resp.content)
        except ET.ParseError as exc:
            raise SaraSoapError(
                f"SOAP 响应不是合法 XML ({self.instrument.host}): {exc}"
            ) from exc

    def get_file_names(self, file_type: str = ".n42") -> list[str]:
        """Call GetFileNames and return remote filenames (basename only)."""
        root = self._soap_post(_build_get_file_names_body(file_type))
        names: list[str] = []
        # Live SARA firmware returns repeated <sara:FilesFound> elements.
        # Older/docs variants may use <FileName> / <FileNames>.
        for local_name in ("FilesFound", "FileName"):
            for el in _find_all_by_local(root, local_name):
                text = (el.text or "").strip()
                if text:
                    names.append(Path(text).name)
            if names:
                break
        # Some firmwares may return a single space-separated FileNames node
        if not names:
            blob = _find_text_by_local(root, "FileNames") or _find_text_by_local(
                root, "GetFileNamesResponse"
            )
            if blob:
                for part in re.split(r"[\s,;]+", blob):
                    part = part.strip()
                    if part.lower().endswith(".n42"):
                        names.append(Path(part).name)
        return names

    def download_files(self, filenames: list[str], dest_dir: Path) -> list[Path]:
        """
        Call DownloadFiles, fetch DownloadPackage, extract matching .n42 files.

        Returns paths of newly written files under ``dest_dir``.
        Never overwrites existing files in ``dest_dir``.

        Live firmware returns ``/tmp/n42Files.tgz`` (gzip tar). Some docs /
        fixtures use zip; both are supported.
        """
        if not filenames:
            return []

        root = self._soap_post(_build_download_files_body(filenames))
        package = _find_text_by_local(root, "DownloadPackage")
        if not package:
            raise SaraSoapError(
                f"DownloadFiles 响应缺少 DownloadPackage ({self.instrument.host})"
            )

        url = resolve_download_package_url(self.instrument.base_url, package)
        try:
            resp = self.session.get(url, timeout=self.timeout, stream=True)
        except requests.RequestException as exc:
            raise SaraSoapError(
                f"下载包失败 ({self.instrument.host}) {url}: {exc}"
            ) from exc

        if resp.status_code != 200:
            raise SaraSoapError(
                f"下载包 HTTP {resp.status_code} ({self.instrument.host}): {url}"
            )

        content_type = (resp.headers.get("Content-Type") or "").lower()
        payload = resp.content
        dest_dir.mkdir(parents=True, exist_ok=True)

        wanted = {name.lower(): name for name in filenames}
        pkg_lower = package.lower()

        is_zip = (
            "zip" in content_type
            or pkg_lower.endswith(".zip")
            or payload[:2] == b"PK"
        )
        is_tgz = (
            "gzip" in content_type
            or "x-tgz" in content_type
            or "x-gtar" in content_type
            or pkg_lower.endswith((".tgz", ".tar.gz", ".tar"))
            or payload[:2] == b"\x1f\x8b"
        )

        if is_zip:
            return self._extract_wanted_from_zip(payload, dest_dir, wanted)
        if is_tgz:
            return self._extract_wanted_from_tarball(payload, dest_dir, wanted)

        # Single-file response: save under the first requested name if one file,
        # or try Content-Disposition filename.
        if len(filenames) == 1:
            base = filenames[0]
        else:
            cd = resp.headers.get("Content-Disposition") or ""
            match = re.search(r'filename="?([^";]+)"?', cd, flags=re.I)
            base = Path(match.group(1)).name if match else filenames[0]

        target = dest_dir / Path(base).name
        if target.exists():
            logger.info("跳过已存在文件 %s @ %s", target.name, self.instrument.host)
            return []
        if not target.name.lower().endswith(".n42"):
            raise SaraSoapError(
                f"非 zip/tgz 响应且文件名不是 .n42: {target.name} "
                f"({self.instrument.host})"
            )
        target.write_bytes(payload)
        return [target]

    def _extract_wanted_from_zip(
        self,
        payload: bytes,
        dest_dir: Path,
        wanted: dict[str, str],
    ) -> list[Path]:
        saved: list[Path] = []
        with tempfile.TemporaryDirectory(prefix="sara_n42_") as tmp:
            zpath = Path(tmp) / "package.zip"
            zpath.write_bytes(payload)
            try:
                with zipfile.ZipFile(zpath, "r") as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        path = self._save_member_if_wanted(
                            dest_dir,
                            wanted,
                            member_name=info.filename,
                            data=zf.read(info),
                        )
                        if path is not None:
                            saved.append(path)
            except zipfile.BadZipFile as exc:
                raise SaraSoapError(
                    f"DownloadPackage 不是有效 zip ({self.instrument.host}): {exc}"
                ) from exc
        return saved

    def _extract_wanted_from_tarball(
        self,
        payload: bytes,
        dest_dir: Path,
        wanted: dict[str, str],
    ) -> list[Path]:
        """Live SARA returns ``/tmp/n42Files.tgz`` (gzip tar), not zip."""
        saved: list[Path] = []
        try:
            try:
                tf = tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz")
            except tarfile.ReadError:
                tf = tarfile.open(fileobj=io.BytesIO(payload), mode="r:*")
            with tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    extracted = tf.extractfile(member)
                    if extracted is None:
                        continue
                    path = self._save_member_if_wanted(
                        dest_dir,
                        wanted,
                        member_name=member.name,
                        data=extracted.read(),
                    )
                    if path is not None:
                        saved.append(path)
        except tarfile.TarError as exc:
            raise SaraSoapError(
                f"DownloadPackage 不是有效 tar/tgz ({self.instrument.host}): {exc}"
            ) from exc
        return saved

    def _save_member_if_wanted(
        self,
        dest_dir: Path,
        wanted: dict[str, str],
        *,
        member_name: str,
        data: bytes,
    ) -> Path | None:
        base = Path(member_name).name
        if base.lower() not in wanted:
            return None
        # Prefer the casing from the requested filename list.
        base = wanted[base.lower()]
        target = dest_dir / base
        if target.exists():
            logger.info(
                "跳过已存在文件 %s @ %s",
                base,
                self.instrument.host,
            )
            return None
        target.write_bytes(data)
        return target
