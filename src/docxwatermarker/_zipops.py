"""
Low-level zip read/write operations with metadata preservation.

This module is INTERNAL. It knows about ZIP file format details but not
about .docx semantics, that lives in core.py.

Design:

The unit of currency is `ZipEntry`, a value object pairing a `zipfile.ZipInfo`
(all metadata) with the entry's raw `bytes`. A whole zip is represented as
an ordered dict { filename: ZipEntry }, which preserves entry order
(important for some consumers of OOXML files) and supports O(1) lookup by
name.

Timestamp policy:

  - Reading a zip preserves every entry's original timestamp in its ZipInfo.
  - Writing a zip preserves those timestamps for every entry, UNLESS the
    entry was constructed via ZipEntry.modified(), in which case its
    timestamp is reset to "now" at write time.
  - Reproducible mode (`write_zip(..., reproducible=True)`) overrides
    everything: all entries get the fixed DOS-min date (1980-01-01), so
    two runs produce byte-identical output. Useful for CI artifacts,
    deterministic build pipelines, and for hash-based copy tracking.

Permissions and compression are always inherited from the source entry
(or from the `template=` argument of ZipEntry.modified() for new content).
"""

from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass, field

# DOS minimum date, used by zipfile as the "zero" timestamp.
_DOS_MIN_DATE = (1980, 1, 1, 0, 0, 0)


@dataclass
class ZipEntry:
    """One entry inside a zip archive: metadata + raw content.

    Use the `modified()` classmethod to produce an entry whose timestamp
    will be set to "now" at write time. Plain instances retain whatever
    timestamp is in `info.date_time`.
    """

    info: zipfile.ZipInfo
    data: bytes
    # Internal flag set by modified() to signal "stamp this as now on write".
    # Callers use the factory method. (Not exposed in the constructor)
    _modified: bool = field(default=False, repr=False)

    @classmethod
    def modified(
        cls,
        *,
        filename: str,
        data: bytes,
        template: "ZipEntry",
    ) -> "ZipEntry":
        """Build a new entry that represents a modification.

        The returned entry will have its timestamp set to "now" by write_zip
        (unless reproducible mode is on). Permissions, compression method,
        and any other ZipInfo flags are inherited from `template`.

        The `template` entry itself is NOT mutated, this is a pure factory.
        """
        # Build a fresh ZipInfo, copying metadata from template but with the
        # potentially-different filename. We start from a new ZipInfo and
        # copy fields explicitly rather than mutating the template's info,
        # to guarantee the template is left untouched.
        info = zipfile.ZipInfo(filename=filename)
        info.compress_type = template.info.compress_type
        info.external_attr = template.info.external_attr
        info.create_system = template.info.create_system
        info.create_version = template.info.create_version
        info.extract_version = template.info.extract_version
        info.flag_bits = template.info.flag_bits
        info.internal_attr = template.info.internal_attr
        # date_time will be overwritten at write time (placeholder for now)
        info.date_time = template.info.date_time
        return cls(info=info, data=data, _modified=True)


def read_zip_entries(data: bytes) -> dict[str, ZipEntry]:
    """Parse a zip archive into an ordered dict of ZipEntry instances.

    The returned dict preserves the order of entries as they appear in the
    central directory. Each ZipEntry holds the original ZipInfo (so all
    metadata, timestamp, permissions, compression, etc, is available)
    and the entry's uncompressed content.

    Raises: zipfile.BadZipFile: if the bytes are not a valid zip archive.
    """
    entries: dict[str, ZipEntry] = {}
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        for info in zf.infolist():
            content = zf.read(info.filename)
            entries[info.filename] = ZipEntry(info=info, data=content)
    return entries


def write_zip(
    entries: dict[str, ZipEntry],
    *,
    reproducible: bool = False,
) -> bytes:
    """Serialize a dict of ZipEntry into a zip archive.

    By default:
      - Entries whose `_modified` flag is True get their timestamp set
        to the current time at the moment of writing.
      - All other entries keep their original timestamp from `info.date_time`.
      - Permissions, compression, and other flags are taken from each entry's
        own ZipInfo.

    With reproducible=True:
      - ALL entries get the fixed DOS-min date (1980-01-01 00:00:00),
        guaranteeing byte-identical output for identical input across runs.
        This overrides the "now" stamp for modified entries.
    """
    if reproducible:
        write_time = _DOS_MIN_DATE
    else:
        write_time = None  # signal: use per-entry policy

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, entry in entries.items():
            # Build a fresh ZipInfo so we don't accidentally mutate the
            # entry's stored info if the caller holds a reference to it.
            out_info = zipfile.ZipInfo(filename=name)
            out_info.compress_type = entry.info.compress_type
            out_info.external_attr = entry.info.external_attr
            out_info.create_system = entry.info.create_system
            out_info.create_version = entry.info.create_version
            out_info.extract_version = entry.info.extract_version
            out_info.flag_bits = entry.info.flag_bits
            out_info.internal_attr = entry.info.internal_attr

            if write_time is not None:
                out_info.date_time = write_time
            elif entry._modified:
                # Use current local time, truncated to whole seconds.
                # zipfile's date_time tuple is (Y, M, D, H, m, s) with
                # 2-second resolution in the DOS time format, but we let
                # zipfile handle that quantization.
                now = time.localtime()
                out_info.date_time = (
                    now.tm_year, now.tm_mon, now.tm_mday,
                    now.tm_hour, now.tm_min, now.tm_sec,
                )
            else:
                out_info.date_time = entry.info.date_time

            zf.writestr(out_info, entry.data)

    return buf.getvalue()
