# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: GPL-2.0-only

"""
journalctl.py  -  ramdump parser for systemd-journald logs.
Includes an embedded pure-Python offline systemd .journal reader
(no systemd / libsystemd dependency required, compatible with Python 3.8+).
"""

import struct
import sys
import os
import json
import traceback
from datetime import datetime, timezone

from parser_util import register_parser, RamParser, cleanupString
from print_out import print_out_str
from utasklib import UTaskLib
from utasklib import ProcessNotFoundExcetion

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------
JOURNAL_MAGIC = b"LPKSHHRH"

def _check(data, off, n, label=""):
    if off < 0 or off + n > len(data):
        raise IndexError(
            "Out-of-bounds read: offset=0x%X size=%d file_size=0x%X %s" % (off, n, len(data), label)
        )

def u8 (d, o):  _check(d, o, 1); return d[o]
def u32(d, o):  _check(d, o, 4); return struct.unpack_from("<I", d, o)[0]
def u64(d, o):  _check(d, o, 8); return struct.unpack_from("<Q", d, o)[0]

# Object types
OBJECT_HEADER_SIZE = 16
OBJECT_UNUSED      = 0
OBJECT_DATA        = 1
OBJECT_FIELD       = 2
OBJECT_ENTRY       = 3
OBJECT_DATA_ARRAY  = 4
OBJECT_FIELD_ARRAY = 5
OBJECT_ENTRY_ARRAY = 6
OBJECT_TAG         = 7

# Compression flags
OBJECT_COMPRESSED_XZ   = 1
OBJECT_COMPRESSED_LZ4  = 2
OBJECT_COMPRESSED_ZSTD = 4

# Incompatible feature flags
INFLAG_KEYED_HASH = 0x04
INFLAG_COMPACT    = 0x10

# Standard layout
ENTRY_ITEM_SIZE_STD        = 16
ENTRY_ARRAY_ITEM_SIZE_STD  = 8
DATA_PAYLOAD_OFF_STD       = 64

# Compact layout
ENTRY_ITEM_SIZE_COMPACT       = 4
ENTRY_ARRAY_ITEM_SIZE_COMPACT = 4
DATA_PAYLOAD_OFF_COMPACT      = 72

# Entry header extra (same for both modes)
ENTRY_HEADER_EXTRA = 48

# Entry array offsets
ENTRY_ARRAY_NEXT_OFF  = OBJECT_HEADER_SIZE
ENTRY_ARRAY_ITEMS_OFF = OBJECT_HEADER_SIZE + 8

# File header offsets
HDR_MAGIC_OFF                 = 0
HDR_COMPAT_FLAGS_OFF          = 8
HDR_INCOMPAT_FLAGS_OFF        = 12
HDR_STATE_OFF                 = 16
HDR_FILE_ID_OFF               = 24
HDR_MACHINE_ID_OFF            = 40
HDR_BOOT_ID_OFF               = 56
HDR_SEQNUM_ID_OFF             = 72
HDR_HEADER_SIZE_OFF           = 88
HDR_ARENA_SIZE_OFF            = 96
HDR_DATA_HASH_TABLE_OFF       = 104
HDR_DATA_HASH_TABLE_SIZE_OFF  = 112
HDR_FIELD_HASH_TABLE_OFF      = 120
HDR_FIELD_HASH_TABLE_SIZE_OFF = 128
HDR_TAIL_OBJECT_OFF           = 136
HDR_N_OBJECTS_OFF             = 144
HDR_N_ENTRIES_OFF             = 152
HDR_TAIL_ENTRY_SEQNUM_OFF     = 160
HDR_HEAD_ENTRY_SEQNUM_OFF     = 168
HDR_HEAD_ENTRY_ARRAY_OFF_OFF  = 176
HDR_HEAD_ENTRY_REALTIME_OFF   = 184
HDR_TAIL_ENTRY_REALTIME_OFF   = 192
HDR_MIN_SIZE = 256


def _id128_str(d, off):
    _check(d, off, 16)
    lo = u64(d, off)
    hi = u64(d, off + 8)
    full = lo | (hi << 64)
    return "%032x" % full


# ---------------------------------------------------------------------------
# Decompression helpers
# ---------------------------------------------------------------------------
def _decompress_lz4(data):
    try:
        import lz4.block
        size = struct.unpack_from("<I", data)[0]
        return lz4.block.decompress(data[4:], uncompressed_size=size)
    except ImportError:
        raise RuntimeError("lz4 not installed: pip install lz4")

def _decompress_xz(data):
    import lzma
    return lzma.decompress(data)

def _decompress_zstd(data):
    try:
        import zstandard as zstd
        return zstd.ZstdDecompressor().decompress(data)
    except ImportError:
        raise RuntimeError("zstandard not installed: pip install zstandard")

def _decompress(raw_payload, flags):
    if flags & OBJECT_COMPRESSED_LZ4:
        return _decompress_lz4(raw_payload)
    elif flags & OBJECT_COMPRESSED_XZ:
        return _decompress_xz(raw_payload)
    elif flags & OBJECT_COMPRESSED_ZSTD:
        return _decompress_zstd(raw_payload)
    return raw_payload


# ---------------------------------------------------------------------------
# JournalFile  -  pure-Python offline .journal reader
# ---------------------------------------------------------------------------
class JournalFile:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.data = f.read()
        self._validate_header()

    def _validate_header(self):
        d = self.data
        if len(d) < HDR_MIN_SIZE:
            raise ValueError("File too small (%d bytes)" % len(d))
        if d[:8] != JOURNAL_MAGIC:
            raise ValueError("Bad magic: %r" % d[:8])
        self.file_size  = len(d)
        self.boot_id    = _id128_str(d, HDR_BOOT_ID_OFF)
        self.machine_id = _id128_str(d, HDR_MACHINE_ID_OFF)
        self._head_entry_array_off = u64(d, HDR_HEAD_ENTRY_ARRAY_OFF_OFF)
        incompat = struct.unpack_from("<I", d, HDR_INCOMPAT_FLAGS_OFF)[0]
        self.is_compact    = bool(incompat & INFLAG_COMPACT)
        self.is_keyed_hash = bool(incompat & INFLAG_KEYED_HASH)
        if self.is_compact:
            self._entry_item_size       = ENTRY_ITEM_SIZE_COMPACT
            self._entry_array_item_size = ENTRY_ARRAY_ITEM_SIZE_COMPACT
            self._data_payload_off      = DATA_PAYLOAD_OFF_COMPACT
        else:
            self._entry_item_size       = ENTRY_ITEM_SIZE_STD
            self._entry_array_item_size = ENTRY_ARRAY_ITEM_SIZE_STD
            self._data_payload_off      = DATA_PAYLOAD_OFF_STD

    def _obj_header(self, off):
        d = self.data
        if off == 0 or off + OBJECT_HEADER_SIZE > len(d):
            return None
        obj_type  = u8(d, off)
        obj_flags = u8(d, off + 1)
        obj_size  = u64(d, off + 8)
        if obj_size < OBJECT_HEADER_SIZE:
            return None
        if off + obj_size > len(d):
            obj_size = len(d) - off
        return obj_type, obj_flags, obj_size

    def _read_data_payload(self, off):
        hdr = self._obj_header(off)
        if hdr is None:
            return None
        obj_type, obj_flags, obj_size = hdr
        if obj_type != OBJECT_DATA:
            return None
        payload_off  = off + self._data_payload_off
        payload_size = (off + obj_size) - payload_off
        if payload_size <= 0:
            return None
        raw = self.data[payload_off: payload_off + payload_size]
        try:
            raw = _decompress(raw, obj_flags)
        except Exception:
            pass
        return raw

    def _read_entry(self, off):
        hdr = self._obj_header(off)
        if hdr is None:
            return None
        obj_type, obj_flags, obj_size = hdr
        if obj_type != OBJECT_ENTRY:
            return None
        d = self.data
        try:
            seqnum    = u64(d, off + OBJECT_HEADER_SIZE)
            realtime  = u64(d, off + OBJECT_HEADER_SIZE + 8)
            monotonic = u64(d, off + OBJECT_HEADER_SIZE + 16)
            boot_id   = _id128_str(d, off + OBJECT_HEADER_SIZE + 24)
        except IndexError:
            return None
        items_off  = off + OBJECT_HEADER_SIZE + ENTRY_HEADER_EXTRA
        items_size = (off + obj_size) - items_off
        if items_size < 0:
            return None
        item_sz = self._entry_item_size
        n_items = items_size // item_sz
        fields = {}
        for i in range(n_items):
            item_off = items_off + i * item_sz
            if item_off + item_sz > len(d):
                break
            if self.is_compact:
                data_obj_off = u32(d, item_off)
            else:
                data_obj_off = u64(d, item_off)
            if data_obj_off == 0:
                continue
            payload = self._read_data_payload(data_obj_off)
            if payload is None:
                continue
            try:
                text = payload.decode("utf-8", errors="replace")
            except Exception:
                continue
            if "=" in text:
                k, _, v = text.partition("=")
                fields[k.strip()] = v.strip()
        if not fields:
            return None
        return {
            "__REALTIME_TIMESTAMP" : str(realtime),
            "__MONOTONIC_TIMESTAMP": str(monotonic),
            "__SEQNUM"             : str(seqnum),
            "_BOOT_ID"             : boot_id,
            **fields,
        }

    def _iter_entry_offsets_by_array(self):
        """Walk the entry-array chain starting from head_entry_array_off.
        Used for active (non-archived) journal files where the chain is valid."""
        arr_off     = self._head_entry_array_off
        seen_arrays = set()
        item_sz     = self._entry_array_item_size
        while arr_off:
            if arr_off in seen_arrays:
                break
            seen_arrays.add(arr_off)
            hdr = self._obj_header(arr_off)
            if hdr is None:
                break
            obj_type, _flags, obj_size = hdr
            if obj_type != OBJECT_ENTRY_ARRAY:
                break
            if arr_off + ENTRY_ARRAY_NEXT_OFF + 8 > len(self.data):
                break
            next_arr_off = u64(self.data, arr_off + ENTRY_ARRAY_NEXT_OFF)
            items_start = arr_off + ENTRY_ARRAY_ITEMS_OFF
            items_end   = arr_off + obj_size
            if items_start < items_end:
                n = (items_end - items_start) // item_sz
                for i in range(n):
                    item_off = items_start + i * item_sz
                    if item_off + item_sz > len(self.data):
                        break
                    if self.is_compact:
                        entry_off = u32(self.data, item_off)
                    else:
                        entry_off = u64(self.data, item_off)
                    if entry_off == 0 or entry_off >= len(self.data):
                        continue
                    yield entry_off
            arr_off = next_arr_off

    def _iter_entry_offsets_linear(self):
        """Linear scan of the entire arena for OBJECT_ENTRY objects.
        Used as fallback for archived journal files where head_entry_array_off == 0.
        Skips over zero-filled pages (common in ramdump) instead of stopping."""
        hdr_size = u64(self.data, HDR_HEADER_SIZE_OFF)
        off = hdr_size
        data_len = len(self.data)
        while off + OBJECT_HEADER_SIZE <= data_len:
            obj_type = u8(self.data, off)
            obj_size = u64(self.data, off + 8)
            # invalid/zero-filled: skip 64 bytes and keep scanning
            if obj_size < OBJECT_HEADER_SIZE:
                off += 64
                continue
            if obj_type == OBJECT_ENTRY:
                yield off
            # align to 64-byte boundary as systemd does
            off += (obj_size + 63) & ~63

    def _iter_entry_offsets(self):
        """Choose iteration strategy based on head_entry_array_off.
        When non-zero, walk the entry-array chain (covers both active and
        archived files that still have a valid chain pointer).
        When zero, fall back to a linear arena scan."""
        if self._head_entry_array_off != 0:
            yield from self._iter_entry_offsets_by_array()
        else:
            yield from self._iter_entry_offsets_linear()

    def entries(self, filters=None, since_us=None, until_us=None):
        flt = {}
        if filters:
            for f in filters:
                if "=" in f:
                    k, _, v = f.partition("=")
                    flt[k.strip().upper()] = v.strip()
        skipped = 0
        for off in self._iter_entry_offsets():
            try:
                entry = self._read_entry(off)
            except Exception:
                skipped += 1
                continue
            if entry is None:
                skipped += 1
                continue
            if since_us or until_us:
                ts = int(entry.get("__REALTIME_TIMESTAMP", 0))
                if since_us and ts < since_us:
                    continue
                if until_us and ts > until_us:
                    continue
            if flt:
                if not all(entry.get(k) == v for k, v in flt.items()):
                    continue
            yield entry
        if skipped:
            print("[journalctl] WARNING: %d corrupt/truncated entries skipped" % skipped,
                  file=sys.stderr)


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------
PRIORITY_NAMES = {
    "0": "EMERG", "1": "ALERT", "2": "CRIT",    "3": "ERR",
    "4": "WARNING","5": "NOTICE","6": "INFO",    "7": "DEBUG",
}

def _ts_human(us_str):
    try:
        dt = datetime.fromtimestamp(int(us_str) / 1e6, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"
    except Exception:
        return us_str

def _ts_monotonic(us_str):
    """Format monotonic timestamp"""
    try:
        us = int(us_str)
        s  = us // 1_000_000
        us_part = us % 1_000_000
        return "[%6d.%06d]" % (s, us_part)
    except Exception:
        return us_str

def fmt_short(entry, color=False):
    monotonic = _ts_monotonic(entry.get("__MONOTONIC_TIMESTAMP", "0"))
    host = entry.get("_HOSTNAME", "?")
    unit = entry.get("_SYSTEMD_UNIT",
           entry.get("SYSLOG_IDENTIFIER",
           entry.get("_COMM", "kernel")))
    pid  = entry.get("_PID", "")
    prio = entry.get("PRIORITY", "6")
    msg  = entry.get("MESSAGE", "")
    pid_str  = "[%s]" % pid if pid else ""
    prio_str = PRIORITY_NAMES.get(prio, prio)
    return "%s %s %s%s: [%s] %s" % (monotonic, host, unit, pid_str, prio_str, msg)


# ---------------------------------------------------------------------------
# Ramdump parser
# ---------------------------------------------------------------------------
@register_parser('--journalctl', 'Extract journalctl logs from ramdump ')
class Journald(RamParser):
    JOURNALCTL_FILE = "systemd.journald"
    JOURNALCTL_LOG  = "journalctl.txt"

    def __init__(self, *args):
        super(Journald, self).__init__(*args)
        self.vma_list    = []
        self.dumped_files = []

    def _read_dentry_name(self, file_ptr):
        """
        Read the full filename from a struct file pointer by walking:
          file -> f_path.dentry -> d_name.name (pointer to actual string)
        Falls back to d_iname inline buffer if the pointer read fails.
        """
        rd = self.ramdump
        try:
            f_path_off  = rd.field_offset('struct file',   'f_path')
            dentry_off  = rd.field_offset('struct path',   'dentry')
            d_name_off  = rd.field_offset('struct dentry', 'd_name')
            d_iname_off = rd.field_offset('struct dentry', 'd_iname')
            if d_iname_off is None:
                d_iname_off = rd.field_offset('struct dentry', 'd_shortname')

            dentry = rd.read_word(file_ptr + f_path_off + dentry_off)
            if not dentry:
                return ""

            # struct qstr: { union { struct{u32 hash; u32 len;}; u64 hash_len; }; const char *name; }
            # Use field_offset to locate qstr.name portably across kernel versions.
            qstr_name_off = rd.field_offset('struct qstr', 'name')
            fname = ""
            if qstr_name_off is not None:
                qstr_addr = dentry + d_name_off
                name_ptr  = rd.read_word(qstr_addr + qstr_name_off)
                if name_ptr:
                    fname = cleanupString(rd.read_cstring(name_ptr, 256))
            # fallback to d_iname
            if not fname and d_iname_off is not None:
                fname = cleanupString(rd.read_cstring(dentry + d_iname_off, 32))
            return fname or ""
        except Exception:
            return ""

    def generate_file(self, mmu):
        if len(self.vma_list) == 0:
            print_out_str("Failed to generate " + self.JOURNALCTL_FILE)
            return
        for vma_info in self.vma_list:
            # use the original journal filename (e.g. system.journal, systemd@2.journal)
            # but change extension to .journald to avoid confusion
            base = os.path.splitext(vma_info['file_name'])[0]
            outfile_name = base + ".journald"
            print_out_str(outfile_name + " base address is {0:x}".format(vma_info['start']))
            self.ramdump.remove_file(outfile_name)
            zero_pages = 0
            with self.ramdump.open_file(outfile_name, 'ab') as out_file:
                addr = vma_info['start']
                end  = addr + vma_info['size']
                while addr < end:
                    phys = mmu.virt_to_phys(addr)
                    if phys is None:
                        out_file.write(b'\x00' * 0x1000)
                        zero_pages += 1
                    else:
                        out_file.write(self.ramdump.read_physical(phys, 0x1000))
                    addr += 0x1000
            if zero_pages:
                print_out_str("[journalctl] {} zero-filled pages in {}".format(
                    zero_pages, outfile_name))
            abs_path = os.path.join(self.ramdump.outdir, outfile_name)
            self.dumped_files.append(abs_path)

    def generate_journalctl_file(self, taskinfo):
        '''
        Dump systemd-journald VMA regions to binary .journald files.
        Reads the real filename via d_name.name pointer to correctly distinguish
        system.journal from systemd@N.journal archive files.
        param taskinfo: utasklib.UTaskInfo
        '''
        seen = set()  # (file_ptr, vm_pgoff) to avoid duplicate VMAs
        for vma in taskinfo.vmalist:
            if not vma.file:
                continue
            # read real filename via d_name.name pointer
            fname = self._read_dentry_name(vma.file)
            print_out_str("[journalctl] vma file={!r} file_ptr=0x{:x} pgoff=0x{:x} start=0x{:x} size=0x{:x}".format(
                fname, vma.file, vma.vm_pgoff, vma.vm_start, vma.vm_end - vma.vm_start))
            if not fname.endswith(".journal"):
                continue
            key = (vma.file, vma.vm_pgoff)
            if key in seen:
                continue
            seen.add(key)
            self.vma_list.append({
                'start'    : vma.vm_start,
                'size'     : vma.vm_end - vma.vm_start,
                'file_name': fname,
            })
            print_out_str("[journalctl] -> matched: {}".format(fname))
        self.generate_file(taskinfo.mmu)

    def parse_journal_to_text(self):
        """
        Parse every dumped binary .journald file and write
        human-readable log lines to journalctl.txt in the output directory.
        """
        if not self.dumped_files:
            print_out_str("[journalctl] No binary journal files to parse")
            return

        log_name = self.JOURNALCTL_LOG
        self.ramdump.remove_file(log_name)

        total  = 0
        errors = 0
        with self.ramdump.open_file(log_name, 'w') as log_file:
            for jfile_path in self.dumped_files:
                print_out_str("[journalctl] Parsing {}".format(jfile_path))
                log_file.write("=== {} ===\n".format(os.path.basename(jfile_path)))
                try:
                    jf = JournalFile(jfile_path)
                    d  = jf.data
                    n_entries = u64(d, HDR_N_ENTRIES_OFF)
                    head_rt   = _ts_human(str(u64(d, HDR_HEAD_ENTRY_REALTIME_OFF)))
                    tail_rt   = _ts_human(str(u64(d, HDR_TAIL_ENTRY_REALTIME_OFF)))
                    log_file.write(
                        "  machine_id : {}\n"
                        "  boot_id    : {}\n"
                        "  compact    : {}\n"
                        "  n_entries  : {}\n"
                        "  time range : {} -> {}\n\n".format(
                            jf.machine_id, jf.boot_id,
                            jf.is_compact, n_entries,
                            head_rt, tail_rt))
                    for entry in jf.entries():
                        log_file.write(fmt_short(entry) + "\n")
                        total += 1

                except Exception as e:
                    errors += 1
                    msg = "[journalctl] ERROR parsing {}: {}".format(
                          os.path.basename(jfile_path), e)
                    print_out_str(msg)
                    log_file.write(msg + "\n")
                    traceback.print_exc()
                log_file.write("\n")

        print_out_str(
            "[journalctl] Wrote {} log entries to {} ({} file(s), {} error(s))".format(
                total, log_name, len(self.dumped_files), errors))

    def parse(self):
        try:
            try:
                taskinfo = UTaskLib(self.ramdump).get_utask_info("systemd-journal")
            except ProcessNotFoundExcetion:
                print_out_str("systemd-journald process is not started")
                return
            self.generate_journalctl_file(taskinfo)
            self.parse_journal_to_text()
        except Exception as result:
            print_out_str(str(result))
            traceback.print_exc()