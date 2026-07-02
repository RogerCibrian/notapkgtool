"""Tests for napt.build.icons module.

Covers the frame selection policy, PNG/ICO parsing, the hand-rolled PE
resource parser, MSI Icon table backends (mocked subprocess), the MSI
administrative-extract fallback, MSIX logo asset extraction, and the
extract_icon_png orchestrator.

All binary fixtures (PNG, ICO, PE, MSIX) are fabricated in-memory or in
tmp_path; no binary files are checked in.
"""

from __future__ import annotations

from pathlib import Path
import struct
import subprocess
from unittest import mock
import zipfile

import pytest

from napt.build.icons import (
    MAX_ICON_BYTES,
    MIN_ICON_PX,
    IconExtraction,
    _assemble_ico,
    _best_frame_from_blob,
    _iter_icon_candidates,
    _msi_cab_icons,
    _msi_icon_blobs_msiinfo,
    _msi_icon_blobs_windows,
    _parse_icon_idt,
    _pe_group_icons,
    _png_frames_from_ico,
    _png_width,
    _select_png_frame,
    extract_icon_png,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _png(width: int, height: int | None = None) -> bytes:
    """Builds a minimal PNG byte stream with a valid signature and IHDR."""
    height = height if height is not None else width
    ihdr_body = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_body + b"\x00\x00\x00\x00"
    iend = struct.pack(">I", 0) + b"IEND" + b"\x00\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + ihdr + iend


def _bmp_frame(size: int = 744) -> bytes:
    """Builds a fake non-PNG (BMP-style) icon frame payload."""
    return b"\x28\x00\x00\x00" + b"\x00" * (size - 4)


def _ico(frames: list[tuple[bytes, int]]) -> bytes:
    """Builds an ICO byte stream from (payload, declared_width) pairs.

    A declared width of 256 or larger is stored as 0 in the 1-byte
    directory field, matching the ICO format.
    """
    count = len(frames)
    header = struct.pack("<HHH", 0, 1, count)
    entries = b""
    offset = 6 + count * 16
    for payload, declared_width in frames:
        width_byte = 0 if declared_width >= 256 else declared_width
        entries += bytes([width_byte, width_byte, 0, 0])
        entries += struct.pack("<HH", 1, 32)
        entries += struct.pack("<II", len(payload), offset)
        offset += len(payload)
    return header + entries + b"".join(payload for payload, _ in frames)


def _pe_with_icons(
    groups: list[list[tuple[bytes, int]]], pe32plus: bool = True
) -> bytes:
    """Builds a minimal PE file containing icon resources.

    Args:
        groups: Icon groups, each a list of (payload, declared_width)
            frame pairs.
        pe32plus: Build a PE32+ (64-bit) optional header when True, else
            PE32.

    Returns:
        Complete PE file bytes with a resource section holding
            RT_GROUP_ICON and RT_ICON entries.
    """
    rsrc_rva = 0x1000
    rsrc_file_offset = 512

    # Assign RT_ICON resource IDs sequentially across all groups.
    icon_payloads: list[tuple[int, bytes]] = []
    group_blobs: list[bytes] = []
    next_id = 1
    for frames in groups:
        entries = b""
        for payload, declared_width in frames:
            width_byte = 0 if declared_width >= 256 else declared_width
            entries += bytes([width_byte, width_byte, 0, 0])
            entries += struct.pack("<HH", 1, 32)
            entries += struct.pack("<IH", len(payload), next_id)
            icon_payloads.append((next_id, payload))
            next_id += 1
        group_blobs.append(struct.pack("<HHH", 0, 1, len(frames)) + entries)

    # Resource section layout (offsets relative to section start):
    # root dir -> [RT_ICON dir, RT_GROUP_ICON dir] -> data entries -> blobs
    root_size = 16 + 2 * 8
    icon_dir_offset = root_size
    icon_dir_size = 16 + len(icon_payloads) * 8
    group_dir_offset = icon_dir_offset + icon_dir_size
    group_dir_size = 16 + len(group_blobs) * 8
    data_entries_offset = group_dir_offset + group_dir_size
    total_leaves = len(icon_payloads) + len(group_blobs)
    blobs_offset = data_entries_offset + total_leaves * 16

    def directory(entries: list[tuple[int, int, bool]]) -> bytes:
        blob = struct.pack("<IIHHHH", 0, 0, 0, 0, 0, len(entries))
        for ident, target, is_dir in entries:
            flagged = target | (0x80000000 if is_dir else 0)
            blob += struct.pack("<II", ident, flagged)
        return blob

    data_entries = b""
    blobs = b""
    leaf_offsets: list[int] = []
    for _ident, payload in icon_payloads:
        leaf_offsets.append(data_entries_offset + len(data_entries) // 1)
        data_entries += struct.pack(
            "<IIII", rsrc_rva + blobs_offset + len(blobs), len(payload), 0, 0
        )
        blobs += payload
    group_leaf_offsets: list[int] = []
    for blob in group_blobs:
        group_leaf_offsets.append(data_entries_offset + len(data_entries))
        data_entries += struct.pack(
            "<IIII", rsrc_rva + blobs_offset + len(blobs), len(blob), 0, 0
        )
        blobs += blob
    # Recompute icon leaf offsets (they were appended before groups)
    leaf_offsets = [data_entries_offset + i * 16 for i in range(len(icon_payloads))]

    root = directory(
        [(3, icon_dir_offset, True), (14, group_dir_offset, True)]
    )
    icon_dir = directory(
        [
            (ident, leaf_offsets[index], False)
            for index, (ident, _payload) in enumerate(icon_payloads)
        ]
    )
    group_dir = directory(
        [
            (index + 1, group_leaf_offsets[index], False)
            for index in range(len(group_blobs))
        ]
    )
    rsrc = root + icon_dir + group_dir + data_entries + blobs

    # PE headers
    e_lfanew = 64
    dos = b"MZ" + b"\x00" * 58 + struct.pack("<I", e_lfanew)
    optional_size = 240 if pe32plus else 224
    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, optional_size, 0)
    magic = 0x20B if pe32plus else 0x10B
    data_dir_rel = 112 if pe32plus else 96
    optional = struct.pack("<H", magic) + b"\x00" * (data_dir_rel - 2)
    directories = bytearray(16 * 8)
    struct.pack_into("<II", directories, 2 * 8, rsrc_rva, len(rsrc))
    optional += bytes(directories)
    optional += b"\x00" * (optional_size - len(optional))
    section = b".rsrc\x00\x00\x00" + struct.pack(
        "<IIII", len(rsrc), rsrc_rva, len(rsrc), rsrc_file_offset
    ) + b"\x00" * 16
    headers = dos + b"PE\x00\x00" + coff + optional + section
    return headers + b"\x00" * (rsrc_file_offset - len(headers)) + rsrc


def _make_msix(path: Path, manifest: str, assets: dict[str, bytes]) -> Path:
    """Creates an MSIX (zip) file with the given manifest and assets."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("AppxManifest.xml", manifest)
        for name, data in assets.items():
            zf.writestr(name, data)
    return path


_MSIX_MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10">
  <Identity Name="Test.App" Version="1.0.0.0" ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>Test App</DisplayName>
    <PublisherDisplayName>Test Publisher</PublisherDisplayName>
    <Logo>{logo}</Logo>
  </Properties>
  <Applications>
    <Application Id="App">
      <uap:VisualElements DisplayName="Test App"
        Square150x150Logo="{square150}"
        Square44x44Logo="{square44}"
        Description="Test" BackgroundColor="transparent" />
    </Application>
  </Applications>
</Package>
"""


def _manifest(
    square150: str = "Assets\\Logo150.png",
    square44: str = "Assets\\Logo44.png",
    logo: str = "Assets\\StoreLogo.png",
) -> str:
    return _MSIX_MANIFEST.format(square150=square150, square44=square44, logo=logo)


# ---------------------------------------------------------------------------
# PNG / ICO / frame selection
# ---------------------------------------------------------------------------


class TestPngWidth:
    """Tests for _png_width."""

    @pytest.mark.parametrize("width", [128, 256, 512])
    def test_reads_width_from_ihdr(self, width):
        """Tests that the IHDR width is read for valid PNG data."""
        assert _png_width(_png(width)) == width

    def test_wrong_magic_returns_none(self):
        """Tests that non-PNG data returns None."""
        assert _png_width(b"\x28\x00" + b"\x00" * 100) is None

    def test_truncated_data_returns_none(self):
        """Tests that truncated PNG data returns None."""
        assert _png_width(_png(256)[:20]) is None


class TestSelectPngFrame:
    """Tests for the _select_png_frame policy."""

    def test_prefers_256_over_larger_and_smaller(self):
        """Tests that 256px wins over both 512px and 150px frames."""
        frames = [(_png(150), 150), (_png(512), 512), (_png(256), 256)]
        selected = _select_png_frame(frames)
        assert selected is not None
        assert selected[1] == 256

    def test_largest_wins_when_all_below_preferred(self):
        """Tests that the largest frame wins when all are below 256px."""
        frames = [(_png(128), 128), (_png(150), 150)]
        selected = _select_png_frame(frames)
        assert selected is not None
        assert selected[1] == 150

    def test_undersized_frames_rejected(self):
        """Tests that frames below the minimum size are rejected."""
        assert _select_png_frame([(_png(48), 48), (_png(96), 96)]) is None

    def test_oversized_file_rejected(self):
        """Tests that frames over the byte cap are rejected."""
        huge = _png(256) + b"\x00" * MAX_ICON_BYTES
        assert _select_png_frame([(huge, 256)]) is None

    def test_empty_returns_none(self):
        """Tests that an empty frame list returns None."""
        assert _select_png_frame([]) is None


class TestPngFramesFromIco:
    """Tests for _png_frames_from_ico."""

    def test_mixed_frames_keeps_only_png(self):
        """Tests that BMP frames are excluded and PNG widths come from IHDR."""
        ico = _ico([(_bmp_frame(), 48), (_png(256), 256)])
        frames, largest = _png_frames_from_ico(ico)
        assert [width for _, width in frames] == [256]
        assert largest == 256

    def test_all_bmp_reports_largest_declared(self):
        """Tests that all-BMP ICOs report the declared width for diagnostics."""
        ico = _ico([(_bmp_frame(), 48), (_bmp_frame(), 32)])
        frames, largest = _png_frames_from_ico(ico)
        assert frames == []
        assert largest == 48

    def test_width_byte_zero_means_256(self):
        """Tests that a zero width byte is treated as 256px."""
        ico = _ico([(_bmp_frame(), 256)])
        _frames, largest = _png_frames_from_ico(ico)
        assert largest == 256

    def test_garbage_returns_empty(self):
        """Tests that non-ICO data returns no frames without raising."""
        assert _png_frames_from_ico(b"garbage") == ([], 0)
        assert _png_frames_from_ico(b"") == ([], 0)

    def test_offset_past_eof_skipped(self):
        """Tests that entries with out-of-range payload offsets are skipped."""
        ico = bytearray(_ico([(_png(256), 256)]))
        struct.pack_into("<I", ico, 6 + 12, len(ico) + 100)
        frames, _largest = _png_frames_from_ico(bytes(ico))
        assert frames == []

    def test_truncated_entry_table_stops(self):
        """Tests that a truncated entry table stops parsing cleanly."""
        ico = _ico([(_png(256), 256)])[:10]
        assert _png_frames_from_ico(ico)[0] == []


# ---------------------------------------------------------------------------
# PE parsing
# ---------------------------------------------------------------------------


class TestPeParser:
    """Tests for the hand-rolled PE icon resource parser."""

    def test_single_group_yields_ico(self):
        """Tests that a PE with one icon group yields a parseable ICO."""
        pe = _pe_with_icons([[(_png(256), 256), (_bmp_frame(), 48)]])
        icos = list(_pe_group_icons(pe))
        assert len(icos) == 1
        frames, _largest = _png_frames_from_ico(icos[0])
        assert [width for _, width in frames] == [256]

    def test_pe32_header_supported(self):
        """Tests that 32-bit PE32 optional headers are parsed."""
        pe = _pe_with_icons([[(_png(256), 256)]], pe32plus=False)
        assert len(list(_pe_group_icons(pe))) == 1

    def test_multiple_groups_in_order(self):
        """Tests that icon groups are yielded in enumeration order."""
        pe = _pe_with_icons([[(_bmp_frame(), 32)], [(_png(256), 256)]])
        icos = list(_pe_group_icons(pe))
        assert len(icos) == 2
        assert _png_frames_from_ico(icos[0])[0] == []
        assert _png_frames_from_ico(icos[1])[0] != []

    def test_group_fallthrough_selects_later_group(self):
        """Tests that a qualifying frame in a later group is selected."""
        pe = _pe_with_icons([[(_bmp_frame(), 32)], [(_png(256), 256)]])
        selected, largest = _best_frame_from_blob(pe)
        assert selected is not None
        assert selected[1] == 256
        assert largest == 256

    def test_not_pe_returns_nothing(self):
        """Tests that non-PE data yields no icon groups."""
        assert list(_pe_group_icons(b"not a pe file")) == []
        assert list(_pe_group_icons(b"MZ" + b"\x00" * 100)) == []

    def test_truncated_pe_returns_nothing(self):
        """Tests that a truncated PE yields no groups without raising."""
        pe = _pe_with_icons([[(_png(256), 256)]])
        assert list(_pe_group_icons(pe[:600])) == []

    def test_assemble_ico_skips_missing_payloads(self):
        """Tests that group entries referencing missing icons are skipped."""
        group = struct.pack("<HHH", 0, 1, 1) + bytes([0, 0, 0, 0]) + struct.pack(
            "<HHIH", 1, 32, 100, 99
        )
        assert _assemble_ico(group, {}) is None

    def test_assemble_ico_rejects_malformed(self):
        """Tests that malformed group data returns None."""
        assert _assemble_ico(b"\x00\x00", {}) is None
        assert _assemble_ico(struct.pack("<HHH", 0, 2, 1), {}) is None


# ---------------------------------------------------------------------------
# Blob dispatch
# ---------------------------------------------------------------------------


class TestBestFrameFromBlob:
    """Tests for _best_frame_from_blob magic dispatch."""

    def test_bare_png_passthrough(self):
        """Tests that a bare PNG blob is selected as-is."""
        png = _png(256)
        selected, largest = _best_frame_from_blob(png)
        assert selected == (png, 256)
        assert largest == 256

    def test_undersized_bare_png_rejected(self):
        """Tests that an undersized bare PNG is rejected but measured."""
        selected, largest = _best_frame_from_blob(_png(32))
        assert selected is None
        assert largest == 32

    def test_ico_blob_parsed(self):
        """Tests that an ICO blob has its best frame selected."""
        ico = _ico([(_png(150), 150), (_png(256), 256)])
        selected, _largest = _best_frame_from_blob(ico)
        assert selected is not None
        assert selected[1] == 256

    def test_unknown_blob_returns_nothing(self):
        """Tests that unknown blob formats return no frame."""
        assert _best_frame_from_blob(b"\x00\x01\x02\x03") == (None, 0)


# ---------------------------------------------------------------------------
# MSI Icon table (tier A)
# ---------------------------------------------------------------------------


class TestParseIconIdt:
    """Tests for _parse_icon_idt."""

    def test_parses_standard_export(self, tmp_path):
        """Tests that a standard 3-header-line idt is parsed."""
        idt = tmp_path / "Icon.idt"
        idt.write_text(
            "Name\tData\ns72\tv0\nIcon\tName\nicon.ico\ticon.ico.ibd\n"
        )
        assert _parse_icon_idt(idt) == {"icon.ico": "icon.ico.ibd"}

    def test_tolerates_leading_codepage_line(self, tmp_path):
        """Tests that a codepage line before the headers is tolerated."""
        idt = tmp_path / "Icon.idt"
        idt.write_text(
            "1252\t_ForceCodepage\nName\tData\ns72\tv0\nIcon\tName\n"
            "app.ico\tapp.ico.ibd\n"
        )
        assert _parse_icon_idt(idt) == {"app.ico": "app.ico.ibd"}

    def test_missing_file_returns_empty(self, tmp_path):
        """Tests that a missing idt file returns an empty mapping."""
        assert _parse_icon_idt(tmp_path / "nope.idt") == {}


class TestIterIconCandidates:
    """Tests for _iter_icon_candidates ordering."""

    def test_arp_icon_first_then_largest(self):
        """Tests that the ARPPRODUCTICON row wins, then largest-first."""
        blobs = {"small": b"x", "big": b"x" * 100, "arp": b"xx"}
        order = [name for name, _ in _iter_icon_candidates(blobs, "arp")]
        assert order == ["arp", "big", "small"]

    def test_no_arp_is_largest_first(self):
        """Tests that without ARPPRODUCTICON, rows come largest-first."""
        blobs = {"small": b"x", "big": b"x" * 100}
        order = [name for name, _ in _iter_icon_candidates(blobs, "")]
        assert order == ["big", "small"]


class TestMsiIconBlobsWindows:
    """Tests for the PowerShell COM Icon table backend (mocked)."""

    def _run_side_effect(self, export_dir, arp, blobs, marker="NAPT_ICON_EXPORTED"):
        def side_effect(cmd, **kwargs):
            if marker == "NAPT_ICON_EXPORTED":
                idt_lines = ["Name\tData", "s72\tv0", "Icon\tName"]
                stream_dir = export_dir / "Icon"
                stream_dir.mkdir(parents=True, exist_ok=True)
                for name, data in blobs.items():
                    idt_lines.append(f"{name}\t{name}.ibd")
                    (stream_dir / f"{name}.ibd").write_bytes(data)
                (export_dir / "Icon.idt").write_text("\n".join(idt_lines) + "\n")
            return subprocess.CompletedProcess(
                cmd, 0, stdout=f"{arp}\n{marker}\n", stderr=""
            )

        return side_effect

    def test_exported_streams_read(self, tmp_path):
        """Tests that exported stream files are read via the idt mapping."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        payload = _ico([(_png(256), 256)])
        with mock.patch(
            "napt.build.icons.subprocess.run",
            side_effect=self._run_side_effect(
                export_dir, "chrome.ico", {"chrome.ico": payload}
            ),
        ):
            arp, blobs = _msi_icon_blobs_windows(tmp_path / "x.msi", export_dir)
        assert arp == "chrome.ico"
        assert blobs == {"chrome.ico": payload}

    def test_no_icon_table_marker(self, tmp_path):
        """Tests that the no-table marker yields an empty blob mapping."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        with mock.patch(
            "napt.build.icons.subprocess.run",
            side_effect=self._run_side_effect(
                export_dir, "", {}, marker="NAPT_NO_ICON_TABLE"
            ),
        ):
            arp, blobs = _msi_icon_blobs_windows(tmp_path / "x.msi", export_dir)
        assert arp == ""
        assert blobs == {}

    def test_malformed_idt_falls_back_to_enumeration(self, tmp_path):
        """Tests that stream files are enumerated when the idt is malformed."""
        export_dir = tmp_path / "export"
        stream_dir = export_dir / "Icon"
        stream_dir.mkdir(parents=True)
        (stream_dir / "app.ico.ibd").write_bytes(b"payload")
        (export_dir / "Icon.idt").write_text("garbage with no tabs\n")

        def side_effect(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0, stdout="\nNAPT_ICON_EXPORTED\n", stderr=""
            )

        with mock.patch(
            "napt.build.icons.subprocess.run", side_effect=side_effect
        ):
            _arp, blobs = _msi_icon_blobs_windows(tmp_path / "x.msi", export_dir)
        assert blobs == {"app.ico": b"payload"}


class TestMsiIconBlobsMsiinfo:
    """Tests for the msitools Icon table backend (mocked)."""

    def test_reads_streams(self, tmp_path):
        """Tests that Property, Icon export, and stream extract compose."""
        payload = _ico([(_png(256), 256)])

        def side_effect(cmd, **kwargs):
            if cmd[1] == "export" and cmd[3] == "Property":
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="ARPPRODUCTICON\tapp.ico\n", stderr=""
                )
            if cmd[1] == "export" and cmd[3] == "Icon":
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout="Name\tData\ns72\tv0\nIcon\tName\napp.ico\tapp.ico\n",
                    stderr="",
                )
            assert cmd[1] == "extract"
            return subprocess.CompletedProcess(cmd, 0, stdout=payload, stderr=b"")

        with (
            mock.patch(
                "napt.build.icons.shutil.which", return_value="/usr/bin/msiinfo"
            ),
            mock.patch("napt.build.icons.subprocess.run", side_effect=side_effect),
        ):
            arp, blobs = _msi_icon_blobs_msiinfo(tmp_path / "x.msi")
        assert arp == "app.ico"
        assert blobs == {"app.ico": payload}

    def test_missing_icon_table_returns_empty(self, tmp_path):
        """Tests that a nonzero Icon export exit means no Icon table."""

        def side_effect(cmd, **kwargs):
            if cmd[1] == "export" and cmd[3] == "Property":
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no table")

        with (
            mock.patch(
                "napt.build.icons.shutil.which", return_value="/usr/bin/msiinfo"
            ),
            mock.patch("napt.build.icons.subprocess.run", side_effect=side_effect),
        ):
            arp, blobs = _msi_icon_blobs_msiinfo(tmp_path / "x.msi")
        assert arp == ""
        assert blobs == {}


class TestMsiCabIcons:
    """Tests for the tier B administrative-extract fallback (mocked)."""

    @staticmethod
    def _extract_side_effect(exes: dict[str, bytes], target_prefix: str):
        def side_effect(cmd, **kwargs):
            target = next(
                (arg for arg in cmd if str(arg).startswith(target_prefix)), None
            )
            assert target is not None
            target_dir = Path(str(target).removeprefix(target_prefix))
            for relative, data in exes.items():
                destination = target_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

        return side_effect

    def _msiexec_side_effect(self, exes: dict[str, bytes]):
        return self._extract_side_effect(exes, "TARGETDIR=")

    def test_best_frame_across_executables_wins(self, tmp_path, monkeypatch):
        """Tests that the policy is applied across all extracted EXEs."""
        import sys

        monkeypatch.setattr(sys, "platform", "win32")
        exes = {
            "Files/App/small.exe": _pe_with_icons([[(_png(150), 150)]]),
            "Files/App/nested/big.exe": _pe_with_icons([[(_png(256), 256)]]),
        }
        with mock.patch(
            "napt.build.icons.subprocess.run",
            side_effect=self._msiexec_side_effect(exes),
        ):
            result = _msi_cab_icons(tmp_path / "x.msi")
        assert result.png is not None
        assert result.width == 256

    def test_msiextract_backend_used_off_windows(self, tmp_path, monkeypatch):
        """Tests that the msiextract backend is used on non-Windows hosts."""
        import sys

        monkeypatch.setattr(sys, "platform", "linux")

        def side_effect(cmd, **kwargs):
            assert cmd[0] == "/usr/bin/msiextract"
            target_dir = Path(cmd[2])
            (target_dir / "app.exe").write_bytes(
                _pe_with_icons([[(_png(256), 256)]])
            )
            return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

        with (
            mock.patch(
                "napt.build.icons.shutil.which", return_value="/usr/bin/msiextract"
            ),
            mock.patch("napt.build.icons.subprocess.run", side_effect=side_effect),
        ):
            result = _msi_cab_icons(tmp_path / "x.msi")
        assert result.width == 256

    def test_no_executables_reports_detail(self, tmp_path, monkeypatch):
        """Tests that an empty extraction reports a clear detail."""
        import sys

        monkeypatch.setattr(sys, "platform", "win32")
        with mock.patch(
            "napt.build.icons.subprocess.run",
            side_effect=self._msiexec_side_effect({}),
        ):
            result = _msi_cab_icons(tmp_path / "x.msi")
        assert result.png is None
        assert "no executables" in result.detail

    def test_extraction_failure_is_caught(self, tmp_path, monkeypatch):
        """Tests that a failed extraction subprocess is caught."""
        import sys

        monkeypatch.setattr(sys, "platform", "win32")
        error = subprocess.CalledProcessError(1603, ["msiexec"])
        with mock.patch("napt.build.icons.subprocess.run", side_effect=error):
            result = _msi_cab_icons(tmp_path / "x.msi")
        assert result.png is None
        assert "administrative extraction failed" in result.detail

    def test_extraction_timeout_is_caught(self, tmp_path, monkeypatch):
        """Tests that an extraction timeout is caught."""
        import sys

        monkeypatch.setattr(sys, "platform", "win32")
        error = subprocess.TimeoutExpired(["msiexec"], 120)
        with mock.patch("napt.build.icons.subprocess.run", side_effect=error):
            result = _msi_cab_icons(tmp_path / "x.msi")
        assert result.png is None
        assert "timed out" in result.detail


# ---------------------------------------------------------------------------
# MSIX
# ---------------------------------------------------------------------------


class TestExtractFromMsix:
    """Tests for MSIX logo asset extraction."""

    def test_targetsize_variant_wins(self, tmp_path):
        """Tests that a targetsize-256 variant beats smaller base assets."""
        msix = _make_msix(
            tmp_path / "app.msix",
            _manifest(),
            {
                "Assets/Logo150.png": _png(150),
                "Assets/Logo44.png": _png(44),
                "Assets/Logo44.targetsize-256.png": _png(256),
            },
        )
        result = extract_icon_png(msix)
        assert result.width == 256
        assert "targetsize-256" in result.detail

    def test_plain_variant_beats_altform_on_tie(self, tmp_path):
        """Tests that plain assets win width ties against altform variants."""
        msix = _make_msix(
            tmp_path / "app.msix",
            _manifest(),
            {
                "Assets/Logo44.targetsize-256_altform-unplated.png": _png(256),
                "Assets/Logo44.targetsize-256.png": _png(256),
                "Assets/Logo150.png": _png(150),
                "Assets/Logo44.png": _png(44),
            },
        )
        result = extract_icon_png(msix)
        assert result.width == 256
        assert "altform" not in result.detail

    def test_undersized_assets_report_detail(self, tmp_path):
        """Tests that only-small assets fail with the size policy named."""
        msix = _make_msix(
            tmp_path / "app.msix",
            _manifest(),
            {"Assets/Logo150.png": _png(44), "Assets/Logo44.png": _png(44)},
        )
        result = extract_icon_png(msix)
        assert result.png is None
        assert f"{MIN_ICON_PX}px" in result.detail

    def test_properties_logo_fallback(self, tmp_path):
        """Tests that Properties/Logo is used when VisualElements are small."""
        msix = _make_msix(
            tmp_path / "app.msix",
            _manifest(),
            {
                "Assets/Logo150.png": _png(44),
                "Assets/Logo44.png": _png(44),
                "Assets/StoreLogo.scale-400.png": _png(200),
            },
        )
        result = extract_icon_png(msix)
        assert result.width == 200

    def test_ms_resource_refs_skipped(self, tmp_path):
        """Tests that ms-resource: logo references are skipped."""
        msix = _make_msix(
            tmp_path / "app.msix",
            _manifest(
                square150="ms-resource:logo",
                square44="ms-resource:logo",
                logo="ms-resource:logo",
            ),
            {},
        )
        result = extract_icon_png(msix)
        assert result.png is None
        assert "no logo assets declared" in result.detail

    def test_case_insensitive_asset_match(self, tmp_path):
        """Tests that zip entries are matched case-insensitively."""
        msix = _make_msix(
            tmp_path / "app.msix",
            _manifest(square150="ASSETS\\LOGO150.PNG"),
            {"assets/logo150.scale-200.png": _png(300), "Assets/Logo44.png": _png(44)},
        )
        result = extract_icon_png(msix)
        assert result.width == 300

    def test_corrupt_zip_is_caught(self, tmp_path):
        """Tests that a corrupt MSIX is caught with a clear detail."""
        bad = tmp_path / "bad.msix"
        bad.write_bytes(b"PK\x03\x04 not really a zip")
        result = extract_icon_png(bad)
        assert result.png is None
        assert "not a valid MSIX archive" in result.detail

    def test_missing_manifest_reports_detail(self, tmp_path):
        """Tests that an MSIX without a manifest reports a clear detail."""
        msix_path = tmp_path / "app.msix"
        with zipfile.ZipFile(msix_path, "w") as zf:
            zf.writestr("other.txt", "hi")
        result = extract_icon_png(msix_path)
        assert result.png is None
        assert "AppxManifest.xml not found" in result.detail


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class TestExtractIconPng:
    """Tests for the extract_icon_png orchestrator."""

    def test_exe_dispatch(self, tmp_path):
        """Tests that .exe files are dispatched to the PE extractor."""
        exe = tmp_path / "setup.exe"
        exe.write_bytes(_pe_with_icons([[(_png(256), 256)]]))
        result = extract_icon_png(exe)
        assert result.png is not None
        assert result.width == 256
        assert "setup.exe" in result.detail

    def test_unsupported_suffix(self, tmp_path):
        """Tests that unsupported installer types report a clear detail."""
        result = extract_icon_png(tmp_path / "app.zip")
        assert result.png is None
        assert "unsupported installer type" in result.detail

    def test_msi_tier_a_to_tier_b_fallthrough(self, tmp_path, monkeypatch):
        """Tests that an empty Icon table falls through to tier B."""
        import napt.build.icons as icons_module

        monkeypatch.setattr(
            icons_module, "_msi_icon_blobs", lambda path: ("", {})
        )
        tier_b_result = IconExtraction(_png(256), 256, "PE icon resource inside")
        monkeypatch.setattr(
            icons_module, "_msi_cab_icons", lambda path: tier_b_result
        )
        result = extract_icon_png(tmp_path / "x.msi")
        assert result is tier_b_result

    def test_internal_exception_is_swallowed(self, tmp_path, monkeypatch):
        """Tests that an unexpected exception becomes a failure result."""
        import napt.build.icons as icons_module

        def boom(path):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(icons_module, "_extract_from_msi", boom)
        result = extract_icon_png(tmp_path / "x.msi")
        assert result.png is None
        assert "kaboom" in result.detail
