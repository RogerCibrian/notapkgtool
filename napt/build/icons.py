# Copyright 2025 Roger Cibrian
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""App icon extraction from installers for NAPT builds.

Extracts a Company Portal-ready PNG icon from MSI, EXE, and MSIX installers
at build time. Only icon frames that are already PNG-encoded are used (no
image re-encoding), and frames must be at least 128px wide and no larger
than 700KB. Among qualifying frames, the one closest to Intune's
recommended 256px is selected.

Extraction sources per installer type:

- MSI: the Icon table (preferring the row named by ARPPRODUCTICON), then a
    fallback administrative extract of the MSI contents scanned for icons in
    the contained executables.
- EXE: RT_GROUP_ICON/RT_ICON resources parsed directly from the PE file.
- MSIX: logo assets declared in AppxManifest.xml, including scale and
    targetsize variants.

Backend Priority (MSI only):

- Windows: PowerShell COM (Windows Installer COM API, always available)
- Linux/macOS: msiinfo/msiextract (from the msitools package)

Example:
    Extract an icon from an installer:
        ```python
        from napt.build.icons import extract_icon_png

        result = extract_icon_png("chrome.msi")
        if result.png is not None:
            print(f"Got a {result.width}px icon from {result.detail}")
        ```

Note:
    Icon extraction is best-effort by design. The public entry point
    [extract_icon_png][napt.build.icons.extract_icon_png] never raises; a
    failure is reported through the returned result so the build can warn
    and continue.

"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from napt.exceptions import PackagingError

# Frame selection policy: PNG-encoded frames only, at least MIN_ICON_PX wide,
# at most MAX_ICON_BYTES on disk (Intune rejects icons over 750KB), preferring
# the frame closest to PREFERRED_ICON_PX from above.
MIN_ICON_PX = 128
PREFERRED_ICON_PX = 256
MAX_ICON_BYTES = 700_000

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_ICO_MAGIC = b"\x00\x00\x01\x00"

# MSIX manifest XML namespaces
_MANIFEST_NS = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
_UAP_NS = "http://schemas.microsoft.com/appx/manifest/uap/windows10"

# PE resource type IDs
_RT_ICON = 3
_RT_GROUP_ICON = 14

# Marker emitted by the PowerShell backend when the MSI has no Icon table
_NO_ICON_TABLE_MARKER = "NAPT_NO_ICON_TABLE"


@dataclass(frozen=True)
class IconExtraction:
    """Represents the outcome of an icon extraction attempt.

    Attributes:
        png: PNG file bytes ready to write to disk, or None if no
            qualifying icon frame was found.
        width: Pixel width of the selected frame, or None on failure.
        detail: Source description on success (e.g. the MSI Icon table row
            or MSIX asset used), or the failure cause on failure.
    """

    png: bytes | None
    width: int | None
    detail: str


def _get_logger():
    """Returns the global logger via lazy import."""
    from napt.logging import get_global_logger

    return get_global_logger()


def extract_icon_png(installer_path: str | Path) -> IconExtraction:
    """Extracts the best available PNG icon from an installer file.

    Dispatches on the installer suffix (.msi, .msix, .exe) and applies the
    module's frame selection policy. This function never raises; failures
    of any kind are reported through the returned result's `detail` field.

    Args:
        installer_path: Path to the installer file.

    Returns:
        Extraction outcome with PNG bytes and frame width on success, or a
            failure cause in `detail` when no qualifying icon was found.

    Example:
        Extract and save an icon:
            ```python
            result = extract_icon_png("installer.msi")
            if result.png is not None:
                Path("icon.png").write_bytes(result.png)
            ```

    """
    logger = _get_logger()
    path = Path(installer_path)
    suffix = path.suffix.lower()
    logger.verbose("BUILD", f"Extracting icon from: {path.name}")
    try:
        if suffix == ".msi":
            return _extract_from_msi(path)
        if suffix == ".msix":
            return _extract_from_msix(path)
        if suffix == ".exe":
            return _extract_from_exe(path)
        return IconExtraction(None, None, f"unsupported installer type '{suffix}'")
    except Exception as err:  # noqa: BLE001 - extraction must never fail the build
        logger.debug("BUILD", f"Icon extraction failed: {err!r}")
        return IconExtraction(None, None, f"extraction failed: {err}")


# ---------------------------------------------------------------------------
# Shared PNG/ICO frame parsing
# ---------------------------------------------------------------------------


def _png_width(data: bytes) -> int | None:
    """Reads the pixel width from a PNG byte stream's IHDR chunk.

    Args:
        data: Candidate PNG file bytes.

    Returns:
        The image width in pixels, or None if the data is not a valid PNG
            header (IHDR is mandated to be the first chunk, so a fixed
            offset read is safe).
    """
    if len(data) < 24 or not data.startswith(_PNG_MAGIC):
        return None
    if data[12:16] != b"IHDR":
        return None
    return struct.unpack_from(">I", data, 16)[0]


def _select_png_frame(
    frames: list[tuple[bytes, int]],
) -> tuple[bytes, int] | None:
    """Selects the best PNG frame according to the module policy.

    Filters to frames at least MIN_ICON_PX wide and at most MAX_ICON_BYTES,
    then prefers the smallest frame that is at least PREFERRED_ICON_PX
    (closest to Intune's recommendation from above), falling back to the
    largest remaining frame.

    Args:
        frames: Candidate (png_bytes, width) pairs.

    Returns:
        The selected (png_bytes, width) pair, or None if nothing qualifies.
    """
    qualifying = [
        (png, width)
        for png, width in frames
        if width >= MIN_ICON_PX and len(png) <= MAX_ICON_BYTES
    ]
    if not qualifying:
        return None
    preferred = [frame for frame in qualifying if frame[1] >= PREFERRED_ICON_PX]
    if preferred:
        return min(preferred, key=lambda frame: frame[1])
    return max(qualifying, key=lambda frame: frame[1])


def _png_frames_from_ico(ico_bytes: bytes) -> tuple[list[tuple[bytes, int]], int]:
    """Extracts PNG-encoded frames from an ICO byte stream.

    Parses the ICONDIR/ICONDIRENTRY structures defensively: malformed
    headers, truncated entries, and out-of-range payload offsets are
    skipped rather than raised.

    Args:
        ico_bytes: A complete .ico file as bytes.

    Returns:
        A tuple (png_frames, largest_px), where
            png_frames is a list of (png_bytes, width) pairs for frames
            that are PNG-encoded (width read from the PNG IHDR, not the
            unreliable 1-byte directory field),
            largest_px is the largest frame width seen in the directory
            regardless of encoding (0 means 256 in the 1-byte field; used
            for diagnostics when no PNG frame qualifies).
    """
    frames: list[tuple[bytes, int]] = []
    largest = 0
    if len(ico_bytes) < 6 or ico_bytes[:4] != _ICO_MAGIC:
        return frames, largest
    (count,) = struct.unpack_from("<H", ico_bytes, 4)
    for index in range(count):
        entry_offset = 6 + index * 16
        if entry_offset + 16 > len(ico_bytes):
            break
        declared_width = ico_bytes[entry_offset] or 256
        largest = max(largest, declared_width)
        size, image_offset = struct.unpack_from("<II", ico_bytes, entry_offset + 8)
        if size == 0 or image_offset + size > len(ico_bytes):
            continue
        payload = ico_bytes[image_offset : image_offset + size]
        width = _png_width(payload)
        if width:
            frames.append((payload, width))
            largest = max(largest, width)
    return frames, largest


def _best_frame_from_blob(blob: bytes) -> tuple[tuple[bytes, int] | None, int]:
    """Selects the best PNG frame from a binary blob of unknown format.

    Dispatches on magic bytes: a bare PNG is used as-is, an ICO is parsed
    for PNG frames, and a PE executable (MZ) has its icon groups parsed
    (first group wins, matching what Explorer displays).

    Args:
        blob: Raw bytes of a PNG, ICO, or PE file.

    Returns:
        A tuple (selected, largest_px), where
            selected is the chosen (png_bytes, width) pair or None,
            largest_px is the largest frame width seen regardless of
            encoding, for diagnostics.
    """
    if blob.startswith(_PNG_MAGIC):
        width = _png_width(blob)
        frames = [(blob, width)] if width else []
        return _select_png_frame(frames), width or 0
    if blob.startswith(_ICO_MAGIC):
        frames, largest = _png_frames_from_ico(blob)
        return _select_png_frame(frames), largest
    if blob.startswith(b"MZ"):
        largest = 0
        for group_ico in _pe_group_icons(blob):
            frames, group_largest = _png_frames_from_ico(group_ico)
            largest = max(largest, group_largest)
            selected = _select_png_frame(frames)
            if selected:
                return selected, largest
        return None, largest
    return None, 0


def _no_frame_detail(largest_px: int, where: str) -> str:
    """Builds a diagnostic string for a failed frame selection.

    Args:
        largest_px: Largest frame width seen regardless of encoding.
        where: Location phrase for the message (e.g. "in the MSI Icon
            table").

    Returns:
        A human-readable failure cause naming the policy requirements.
    """
    if largest_px:
        return (
            f"largest icon frame {where} is {largest_px}px "
            f"(PNG-encoded frames of at least {MIN_ICON_PX}px and at most "
            f"{MAX_ICON_BYTES // 1000}KB are required)"
        )
    return f"no icon frames found {where}"


# ---------------------------------------------------------------------------
# EXE (PE resource) extraction
# ---------------------------------------------------------------------------


def _extract_from_exe(exe_path: Path) -> IconExtraction:
    """Extracts an icon from a PE executable's resources.

    Args:
        exe_path: Path to the .exe file.

    Returns:
        Extraction outcome; the detail names the source file on success.
    """
    selected, largest = _best_frame_from_blob(exe_path.read_bytes())
    if selected:
        return IconExtraction(
            selected[0], selected[1], f"PE icon resource in {exe_path.name}"
        )
    return IconExtraction(None, None, _no_frame_detail(largest, f"in {exe_path.name}"))


def _pe_group_icons(data: bytes) -> Iterator[bytes]:
    """Yields reassembled ICO byte streams from a PE file's icon resources.

    Walks the PE headers to the resource directory tree, collects
    RT_GROUP_ICON directories (in enumeration order, so the executable's
    primary icon group comes first) and their referenced RT_ICON payloads,
    and reassembles each group into a standard .ico byte stream.

    Any structural surprise (truncation, bad offsets, unknown headers)
    ends the iteration silently; this parser targets well-formed vendor
    installers, not adversarial input.

    Args:
        data: Complete PE file bytes.

    Yields:
        Standard .ico byte streams, one per icon group.
    """
    try:
        groups, icons = _pe_icon_resources(data)
    except (struct.error, IndexError, ValueError, OverflowError):
        return
    for group in groups:
        ico = _assemble_ico(group, icons)
        if ico is not None:
            yield ico


def _pe_icon_resources(data: bytes) -> tuple[list[bytes], dict[int, bytes]]:
    """Collects raw icon resources from a PE file.

    Args:
        data: Complete PE file bytes.

    Returns:
        A tuple (groups, icons), where
            groups is a list of GRPICONDIR blobs in enumeration order,
            icons maps RT_ICON resource IDs to their raw image payloads.

    Raises:
        struct.error: If a header read runs past the end of the data.
        ValueError: If a resource directory declares an implausible number
            of entries.
    """
    if len(data) < 0x40 or data[:2] != b"MZ":
        return [], {}
    (e_lfanew,) = struct.unpack_from("<I", data, 0x3C)
    if data[e_lfanew : e_lfanew + 4] != b"PE\x00\x00":
        return [], {}
    coff_offset = e_lfanew + 4
    (num_sections,) = struct.unpack_from("<H", data, coff_offset + 2)
    (optional_size,) = struct.unpack_from("<H", data, coff_offset + 16)
    optional_offset = coff_offset + 20
    (magic,) = struct.unpack_from("<H", data, optional_offset)
    if magic == 0x10B:  # PE32
        data_dir_offset = optional_offset + 96
    elif magic == 0x20B:  # PE32+
        data_dir_offset = optional_offset + 112
    else:
        return [], {}
    # Data directory index 2 is the resource directory
    resource_rva, _resource_size = struct.unpack_from(
        "<II", data, data_dir_offset + 2 * 8
    )
    if not resource_rva:
        return [], {}

    sections: list[tuple[int, int, int]] = []
    section_table = optional_offset + optional_size
    for index in range(num_sections):
        base = section_table + index * 40
        virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from(
            "<IIII", data, base + 8
        )
        sections.append((virtual_address, max(virtual_size, raw_size), raw_pointer))

    def rva_to_offset(rva: int) -> int | None:
        for virtual_address, size, raw_pointer in sections:
            if virtual_address <= rva < virtual_address + size:
                return raw_pointer + (rva - virtual_address)
        return None

    resource_offset = rva_to_offset(resource_rva)
    if resource_offset is None:
        return [], {}

    def directory_entries(relative: int) -> list[tuple[int, int, bool]]:
        base = resource_offset + relative
        named_count, id_count = struct.unpack_from("<HH", data, base + 12)
        if named_count + id_count > 0x1000:
            raise ValueError("implausible resource directory entry count")
        entries: list[tuple[int, int, bool]] = []
        for index in range(named_count + id_count):
            ident, target = struct.unpack_from("<II", data, base + 16 + index * 8)
            entries.append((ident, target & 0x7FFFFFFF, bool(target & 0x80000000)))
        return entries

    def first_leaf(entry: tuple[int, int, bool], depth: int) -> bytes | None:
        _ident, relative, is_directory = entry
        if not is_directory:
            data_rva, size = struct.unpack_from(
                "<II", data, resource_offset + relative
            )
            offset = rva_to_offset(data_rva)
            if offset is None or offset + size > len(data):
                return None
            return data[offset : offset + size]
        if depth >= 3:
            return None
        for sub_entry in directory_entries(relative):
            blob = first_leaf(sub_entry, depth + 1)
            if blob is not None:
                return blob
        return None

    groups: list[bytes] = []
    icons: dict[int, bytes] = {}
    for ident, relative, is_directory in directory_entries(0):
        if not is_directory:
            continue
        if ident == _RT_GROUP_ICON:
            for entry in directory_entries(relative):
                blob = first_leaf(entry, 1)
                if blob is not None:
                    groups.append(blob)
        elif ident == _RT_ICON:
            for entry in directory_entries(relative):
                blob = first_leaf(entry, 1)
                if blob is not None:
                    icons[entry[0]] = blob
    return groups, icons


def _assemble_ico(group: bytes, icons: dict[int, bytes]) -> bytes | None:
    """Reassembles a standard .ico stream from a GRPICONDIR and icon payloads.

    A GRPICONDIRENTRY is the 16-byte ICONDIRENTRY with the trailing 4-byte
    image offset replaced by a 2-byte RT_ICON resource ID; this function
    reverses that transformation.

    Args:
        group: Raw GRPICONDIR resource bytes.
        icons: RT_ICON resource ID to raw image payload mapping.

    Returns:
        A complete .ico byte stream, or None if the group is malformed or
            references no available payloads.
    """
    if len(group) < 6:
        return None
    _reserved, icon_type, declared_count = struct.unpack_from("<HHH", group, 0)
    if icon_type != 1 or declared_count == 0:
        return None
    picked: list[tuple[bytes, bytes]] = []
    for index in range(declared_count):
        entry_offset = 6 + index * 14
        if entry_offset + 14 > len(group):
            break
        header = group[entry_offset : entry_offset + 8]
        (icon_id,) = struct.unpack_from("<H", group, entry_offset + 12)
        payload = icons.get(icon_id)
        if payload:
            picked.append((header, payload))
    if not picked:
        return None
    count = len(picked)
    ico = bytearray(struct.pack("<HHH", 0, 1, count))
    payload_offset = 6 + count * 16
    for header, payload in picked:
        ico += header + struct.pack("<II", len(payload), payload_offset)
        payload_offset += len(payload)
    for _header, payload in picked:
        ico += payload
    return bytes(ico)


# ---------------------------------------------------------------------------
# MSI extraction (tier A: Icon table, tier B: administrative extract)
# ---------------------------------------------------------------------------


def _extract_from_msi(msi_path: Path) -> IconExtraction:
    """Extracts an icon from an MSI, trying the Icon table then the contents.

    Tier A reads the MSI Icon table (preferring the ARPPRODUCTICON row).
    If that yields no qualifying frame — including when the Icon table
    backend itself fails — tier B performs an administrative extract of
    the MSI and scans the contained executables.

    Args:
        msi_path: Path to the .msi file.

    Returns:
        Extraction outcome; on failure the detail combines both tiers'
            causes.
    """
    logger = _get_logger()
    tier_a_detail = "no Icon table in MSI"
    arp_icon = ""
    blobs: dict[str, bytes] = {}
    try:
        arp_icon, blobs = _msi_icon_blobs(msi_path)
    except (PackagingError, NotImplementedError) as err:
        logger.debug("BUILD", f"Icon table read failed: {err!r}")
        tier_a_detail = f"Icon table read failed ({err})"
    largest = 0
    for name, blob in _iter_icon_candidates(blobs, arp_icon):
        selected, blob_largest = _best_frame_from_blob(blob)
        largest = max(largest, blob_largest)
        if selected:
            return IconExtraction(
                selected[0], selected[1], f"MSI Icon table row '{name}'"
            )
    if blobs:
        tier_a_detail = _no_frame_detail(largest, "in the MSI Icon table")
    logger.debug(
        "BUILD", "MSI Icon table yielded no icon; trying administrative extract..."
    )
    tier_b = _msi_cab_icons(msi_path)
    if tier_b.png is not None:
        return tier_b
    return IconExtraction(None, None, f"{tier_a_detail}; {tier_b.detail}")


def _msi_icon_blobs(msi_path: Path) -> tuple[str, dict[str, bytes]]:
    """Reads the MSI Icon table's binary streams.

    Args:
        msi_path: Path to the .msi file.

    Returns:
        A tuple (arp_icon, blobs), where
            arp_icon is the ARPPRODUCTICON property value ("" if unset),
            blobs maps Icon table row names to their binary data (empty if
            the MSI has no Icon table).

    Raises:
        PackagingError: If the backend subprocess fails.
        NotImplementedError: If no extraction backend is available on this
            system.
    """
    if sys.platform.startswith("win"):
        with tempfile.TemporaryDirectory(prefix="napt-icon-") as tmp:
            return _msi_icon_blobs_windows(msi_path, Path(tmp))
    if shutil.which("msiinfo"):
        return _msi_icon_blobs_msiinfo(msi_path)
    raise NotImplementedError(
        "MSI icon extraction is not available on this host. "
        "On Windows, ensure PowerShell is available. "
        "On Linux/macOS, install 'msitools'."
    )


def _msi_icon_blobs_windows(
    msi_path: Path, export_dir: Path
) -> tuple[str, dict[str, bytes]]:
    """Reads Icon table streams via the Windows Installer COM API.

    Uses Database.Export, which writes each binary stream to a file under
    ``export_dir/Icon/`` (conventionally named ``<row name>.ibd``) instead
    of piping bytes through stdout, where the COM string marshaling would
    corrupt them.

    Args:
        msi_path: Path to the .msi file.
        export_dir: Scratch directory to export the Icon table into.

    Returns:
        The ARPPRODUCTICON value and the Icon table row-name-to-bytes
            mapping (empty when the MSI has no Icon table).

    Raises:
        PackagingError: If the PowerShell subprocess fails or times out.
    """
    logger = _get_logger()
    logger.debug("BUILD", "Trying backend: PowerShell COM (Database.Export)...")
    escaped_msi = str(msi_path).replace("'", "''")
    escaped_dir = str(export_dir).replace("'", "''")
    ps_script = f"""
$installer = New-Object -ComObject WindowsInstaller.Installer
$db = $installer.OpenDatabase('{escaped_msi}', 0)
if ($null -eq $db) {{
    Write-Error "Failed to open database"
    exit 1
}}
$view = $db.OpenView("SELECT Value FROM Property WHERE Property = 'ARPPRODUCTICON'")
$view.Execute()
$record = $view.Fetch()
if ($record) {{ $record.StringData(1) }} else {{ '' }}
$view.Close()
if ($db.TablePersistent('Icon') -ne 1) {{
    '{_NO_ICON_TABLE_MARKER}'
}} else {{
    $db.Export('Icon', '{escaped_dir}', 'Icon.idt')
    'NAPT_ICON_EXPORTED'
}}
"""
    try:
        ps_result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as err:
        stderr_output = err.stderr if err.stderr else "No stderr captured"
        raise PackagingError(
            f"PowerShell MSI icon export failed (exit {err.returncode}). "
            f"stderr: {stderr_output}"
        ) from err
    except subprocess.TimeoutExpired:
        raise PackagingError("PowerShell MSI icon export timed out") from None

    lines = ps_result.stdout.splitlines()
    arp_icon = lines[0].strip() if lines else ""
    marker = lines[1].strip() if len(lines) > 1 else ""
    if marker == _NO_ICON_TABLE_MARKER:
        return arp_icon, {}

    names = _parse_icon_idt(export_dir / "Icon.idt")
    stream_dir = export_dir / "Icon"
    blobs: dict[str, bytes] = {}
    for name, file_name in names.items():
        stream_path = stream_dir / file_name
        if stream_path.exists():
            blobs[name] = stream_path.read_bytes()
    if not blobs and stream_dir.is_dir():
        # Fallback: the .idt didn't parse as expected; take the exported
        # stream files directly, stripping the conventional .ibd suffix.
        for stream_path in sorted(stream_dir.iterdir()):
            if stream_path.is_file():
                name = stream_path.name.removesuffix(".ibd")
                blobs[name] = stream_path.read_bytes()
    return arp_icon, blobs


def _parse_icon_idt(idt_path: Path) -> dict[str, str]:
    """Parses an exported Icon.idt into a row-name-to-stream-file mapping.

    The .idt archive format is tab-separated with three header lines
    (column names, column formats, table name and keys); an optional
    codepage line may precede them.

    Args:
        idt_path: Path to the exported Icon.idt file.

    Returns:
        Icon table row names mapped to their exported stream file names
            (empty if the file is missing or has no data rows).
    """
    if not idt_path.exists():
        return {}
    lines = idt_path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows_start = 3
    for index, line in enumerate(lines[:4]):
        if line.split("\t", 1)[0].strip() == "Icon":
            rows_start = index + 1
            break
    mapping: dict[str, str] = {}
    for line in lines[rows_start:]:
        columns = line.split("\t")
        if len(columns) >= 2 and columns[0]:
            mapping[columns[0]] = columns[1]
    return mapping


def _msi_icon_blobs_msiinfo(msi_path: Path) -> tuple[str, dict[str, bytes]]:
    """Reads Icon table streams via msitools (Linux/macOS).

    Args:
        msi_path: Path to the .msi file.

    Returns:
        The ARPPRODUCTICON value and the Icon table row-name-to-bytes
            mapping (empty when the MSI has no Icon table).

    Raises:
        PackagingError: If reading the Property table or a stream fails.
    """
    logger = _get_logger()
    logger.debug("BUILD", "Trying backend: msiinfo (msitools)...")
    msiinfo_bin = shutil.which("msiinfo")
    if not msiinfo_bin:
        raise PackagingError("msiinfo is not available")

    try:
        property_result = subprocess.run(
            [msiinfo_bin, "export", str(msi_path), "Property"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as err:
        raise PackagingError(f"msiinfo Property export failed: {err}") from err
    arp_icon = ""
    for line in property_result.stdout.splitlines():
        columns = line.strip().split("\t", 1)
        if len(columns) == 2 and columns[0] == "ARPPRODUCTICON":
            arp_icon = columns[1]
            break

    # A nonzero exit here means the Icon table does not exist.
    icon_result = subprocess.run(
        [msiinfo_bin, "export", str(msi_path), "Icon"],
        check=False,
        capture_output=True,
        text=True,
    )
    if icon_result.returncode != 0:
        return arp_icon, {}

    lines = icon_result.stdout.splitlines()
    rows_start = 3
    for index, line in enumerate(lines[:4]):
        if line.split("\t", 1)[0].strip() == "Icon":
            rows_start = index + 1
            break
    blobs: dict[str, bytes] = {}
    for line in lines[rows_start:]:
        name = line.split("\t", 1)[0].strip()
        if not name:
            continue
        try:
            extract_result = subprocess.run(
                [msiinfo_bin, "extract", str(msi_path), f"Icon.{name}"],
                check=True,
                capture_output=True,
                text=False,
            )
        except subprocess.CalledProcessError as err:
            raise PackagingError(f"msiinfo stream extract failed: {err}") from err
        blobs[name] = extract_result.stdout
    return arp_icon, blobs


def _iter_icon_candidates(
    blobs: dict[str, bytes], arp_icon: str
) -> Iterator[tuple[str, bytes]]:
    """Yields Icon table blobs in preference order.

    The ARPPRODUCTICON row is the authoritative product icon and comes
    first when present; remaining rows follow largest-first.

    Args:
        blobs: Icon table row names mapped to binary data.
        arp_icon: ARPPRODUCTICON property value ("" if unset).

    Yields:
        (row name, blob) pairs in preference order.
    """
    ordered = sorted(blobs.items(), key=lambda item: len(item[1]), reverse=True)
    if arp_icon and arp_icon in blobs:
        yield arp_icon, blobs[arp_icon]
        ordered = [(name, blob) for name, blob in ordered if name != arp_icon]
    yield from ordered


def _msi_cab_icons(msi_path: Path) -> IconExtraction:
    """Extracts MSI contents and scans the contained executables for icons.

    Performs an administrative extract (``msiexec /a`` on Windows,
    ``msiextract`` elsewhere) into a temporary directory and applies the
    frame selection policy across the icons of every extracted executable.

    Args:
        msi_path: Path to the .msi file.

    Returns:
        Extraction outcome; failures report the extraction or scan cause.
    """
    logger = _get_logger()
    with tempfile.TemporaryDirectory(prefix="napt-msiadmin-") as tmp:
        extract_dir = Path(tmp)
        try:
            if sys.platform.startswith("win"):
                logger.debug("BUILD", "Administrative extract via msiexec /a...")
                # msiexec requires TARGETDIR="value" quoting when the path
                # contains spaces; a list argument would be re-quoted as one
                # token ("TARGETDIR=C:\..."), which msiexec rejects. Pass a
                # command string so the quotes reach msiexec verbatim.
                command = (
                    f'msiexec /a "{msi_path.resolve()}" /qn '
                    f'TARGETDIR="{extract_dir.resolve()}"'
                )
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
            else:
                msiextract_bin = shutil.which("msiextract")
                if not msiextract_bin:
                    return IconExtraction(
                        None, None, "msiextract (msitools) is not installed"
                    )
                logger.debug("BUILD", "Administrative extract via msiextract...")
                subprocess.run(
                    [msiextract_bin, "-C", str(extract_dir), str(msi_path)],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
        except subprocess.CalledProcessError as err:
            return IconExtraction(
                None,
                None,
                f"administrative extraction failed (exit {err.returncode})",
            )
        except subprocess.TimeoutExpired:
            return IconExtraction(None, None, "administrative extraction timed out")

        executables = sorted(extract_dir.rglob("*.exe"))
        if not executables:
            return IconExtraction(
                None, None, "administrative extraction produced no executables"
            )
        candidates: list[tuple[bytes, int]] = []
        largest = 0
        for executable in executables:
            selected, exe_largest = _best_frame_from_blob(executable.read_bytes())
            largest = max(largest, exe_largest)
            if selected:
                candidates.append(selected)
        final = _select_png_frame(candidates)
        if final:
            return IconExtraction(
                final[0], final[1], "PE icon resource inside the MSI contents"
            )
        return IconExtraction(
            None, None, _no_frame_detail(largest, "in the MSI contents")
        )


# ---------------------------------------------------------------------------
# MSIX extraction
# ---------------------------------------------------------------------------


def _extract_from_msix(msix_path: Path) -> IconExtraction:
    """Extracts an icon from an MSIX package's logo assets.

    Reads the logo references from AppxManifest.xml and applies the frame
    selection policy across the scale and targetsize variants of every
    reference, so the best-resolution variant wins regardless of which
    manifest attribute declared it.

    Args:
        msix_path: Path to the .msix file.

    Returns:
        Extraction outcome; the detail names the chosen asset on success.
    """
    try:
        with zipfile.ZipFile(msix_path, "r") as zf:
            if "AppxManifest.xml" not in zf.namelist():
                return IconExtraction(
                    None, None, "AppxManifest.xml not found in MSIX"
                )
            try:
                root = ET.fromstring(zf.read("AppxManifest.xml"))
            except ET.ParseError:
                return IconExtraction(
                    None, None, "could not parse AppxManifest.xml"
                )
            candidates = _msix_logo_candidates(root)
            if not candidates:
                return IconExtraction(
                    None, None, "no logo assets declared in AppxManifest.xml"
                )
            triples: list[tuple[bytes, int, str]] = []
            for candidate in candidates:
                triples.extend(_msix_asset_variants(zf, candidate))
            # Stable sort so plain assets win width ties against altform
            # variants (taskbar-specific plating).
            triples.sort(key=lambda triple: "altform-" in triple[2].lower())
            largest = max((width for _, width, _ in triples), default=0)
            selected = _select_png_frame(
                [(data, width) for data, width, _ in triples]
            )
            if selected:
                name = next(
                    name for data, _width, name in triples if data is selected[0]
                )
                return IconExtraction(
                    selected[0], selected[1], f"MSIX asset {name}"
                )
            return IconExtraction(
                None, None, _no_frame_detail(largest, "in the MSIX logo assets")
            )
    except zipfile.BadZipFile:
        return IconExtraction(None, None, "not a valid MSIX archive")


def _msix_logo_candidates(root: ET.Element) -> list[str]:
    """Collects logo asset references from an MSIX manifest in priority order.

    Priority: the first Application's VisualElements Square150x150Logo and
    Square44x44Logo attributes, then the package-level Properties/Logo
    element. References to localized resources (``ms-resource:``) are
    skipped and backslashes are normalized to forward slashes.

    Args:
        root: Parsed AppxManifest.xml root element.

    Returns:
        Zip-relative logo paths, deduplicated, in priority order.
    """
    candidates: list[str] = []
    applications = root.find(f"{{{_MANIFEST_NS}}}Applications")
    if applications is not None:
        for application in applications.findall(f"{{{_MANIFEST_NS}}}Application"):
            visual = application.find(f"{{{_UAP_NS}}}VisualElements")
            if visual is None:
                continue
            for attribute in ("Square150x150Logo", "Square44x44Logo"):
                value = visual.get(attribute)
                if value and not value.startswith("ms-resource:"):
                    candidates.append(value.replace("\\", "/"))
            break
    properties = root.find(f"{{{_MANIFEST_NS}}}Properties")
    if properties is not None:
        logo = properties.find(f"{{{_MANIFEST_NS}}}Logo")
        if (
            logo is not None
            and logo.text
            and not logo.text.startswith("ms-resource:")
        ):
            candidates.append(logo.text.strip().replace("\\", "/"))
    return list(dict.fromkeys(candidates))


def _msix_asset_variants(
    zf: zipfile.ZipFile, candidate: str
) -> list[tuple[bytes, int, str]]:
    """Collects PNG variants of a logo asset reference from an MSIX package.

    Matches the exact reference plus scale and targetsize variants
    (``Foo.scale-200.png``, ``Foo.targetsize-256_altform-unplated.png``),
    case-insensitively.

    Args:
        zf: Open MSIX zip file.
        candidate: Zip-relative logo path from the manifest.

    Returns:
        (png_bytes, width, entry_name) triples for every readable PNG
            variant.
    """
    candidate_lower = candidate.lower()
    stem_lower = candidate_lower.rsplit(".", 1)[0]
    triples: list[tuple[bytes, int, str]] = []
    for entry_name in zf.namelist():
        normalized = entry_name.replace("\\", "/").lower()
        if normalized != candidate_lower and not (
            normalized.startswith(stem_lower + ".") and normalized.endswith(".png")
        ):
            continue
        data = zf.read(entry_name)
        width = _png_width(data)
        if width:
            triples.append((data, width, entry_name))
    return triples
