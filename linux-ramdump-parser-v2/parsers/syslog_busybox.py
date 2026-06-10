# SPDX-License-Identifier: GPL-2.0-only
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.

# Combined BusyBox syslog extractors for RAMDUMP:
#
# 1) RAM buffer (syslogd -C):
#    - Extracts BusyBox syslogd -C shared-memory circular buffer (the same buffer
#      that BusyBox logread reads).
#    - Layout (shbuf_ds): int32 size; int32 tail; char data[] (NUL-separated strings).
#    - Output: /SYSLOG/RAM/messages.txt
#
# 2) File-based syslog:
#    - Extracts /var/log/messages or /log/messages plus all rotated siblings
#      (messages.*, syslog.*) from the parent directory using inode + xarray.
#    - Outputs:
#        /SYSLOG/FILE/messages_file.txt         (current file)
#        /SYSLOG/FILE/messages_file.<n>.txt     (rotations)
#

from __future__ import print_function

import os
import struct
import traceback
import mm

from parser_util import register_parser, RamParser, cleanupString
from print_out import print_out_str
from utasklib import UTaskLib, ProcessNotFoundExcetion

class Syslog_busybox(RamParser):

    # Parameters for RAM buffer (syslogd -C)
    DEFAULT_C_KB = 300
    DEFAULT_C_BYTES = DEFAULT_C_KB * 1024
    SCAN_CHUNK = 2 * 1024 * 1024
    SAMPLE = 4096
    MIN_BUF = 4 * 1024
    MAX_BUF = 4 * 1024 * 1024

    def __init__(self, ramdump, taskinfo=None):

        """RamParser expects only (ramdump). We accept an optional second argument to
        remain compatible with call sites that pass task info, but the current
        implementation does not require it.
        """
        super().__init__(ramdump)
        self.taskinfo = taskinfo

    def parse(self):
        """
        Entry point: creates base folders and runs:
        1) RAM buffer extractor (syslogd -C)
        2) File-based syslog extractor (messages + rotations)
        """
        # Output directly under <outdir>/SYSLOG/*
        syslog_base = os.path.join(self.ramdump.outdir, "SYSLOG")
        ram_dir = os.path.join(syslog_base, "RAM")
        file_dir = os.path.join(syslog_base, "FILE")

        for d in (syslog_base, ram_dir, file_dir):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                if not os.path.isdir(d):
                    os.makedirs(d)

        # 1) RAM buffer (syslogd -C)
        try:
            self._extract_ram_buffer(ram_dir)
        except ProcessNotFoundExcetion:
            print_out_str("syslogd process not found; skipping RAM buffer extraction")
        except Exception as e:
            print_out_str(" RAM buffer unexpected error: %s" % e)
            traceback.print_exc()

        # 2) File-based syslog (/var/log/messages or /log/messages + rotations)
        try:
            self._extract_syslog_file(file_dir)
        except ProcessNotFoundExcetion:
            print_out_str("syslogd/rsyslogd not found; skipping file-based syslog extraction")
        except Exception as e:
            print_out_str(" File-based syslog unexpected error: %s" % e)
            traceback.print_exc()

    # =====================================================================
    # PART 1: RAM buffer (syslogd -C)
    # =====================================================================
    def _extract_ram_buffer(self, outdir):
        print_out_str("=== RAM buffer extraction (syslogd -C) ===")
        out = os.path.join(outdir, "messages.txt")
        # If logread/syslogd -C buffer is not enabled (common on legacy targets),
        # do NOT create/overwrite the RAM messages.txt output.
        if self._logread_likely_disabled():
            try:
                if os.path.exists(out):
                    os.remove(out)
            except Exception:
                pass
            print_out_str("Legacy target detected -> skipping RAM logread buffer !! ")
            return


        # A) Try via syslogd VMAs
        found = self._find_shbuf_via_syslogd()
        if found:
            kind, base, size, tail, mmu = found
            data = self._read_data(kind, mmu, base, size)
            msgs = self._reconstruct(data, size, tail)
            self._write_msgs(out, msgs)
            print_out_str("RAM buffer OK: %s (lines=%d) base=0x%x size=%d tail=%d" %
                          (out, len(msgs), base, size, tail))
            return

        # B) Fallback: physical scan
        found = self._find_shbuf_phys()
        if found:
            pbase, size, tail = found
            data = self.ramdump.read_physical(pbase + 8, size)
            if not data:
                print_out_str("RAM buffer header found, but payload read failed")
                return
            msgs = self._reconstruct(data, size, tail)
            self._write_msgs(out, msgs)
            print_out_str("RAM buffer OK (phys): %s (lines=%d) base=0x%x size=%d tail=%d" %
                          (out, len(msgs), pbase, size, tail))
            return

        print_out_str("RAM buffer NOT FOUND (syslogd -C missing or not in dump)")

    def _logread_likely_disabled(self):
        """
        Heuristic to decide if BusyBox logread/syslogd -C shared buffer is likely NOT enabled.

        Why: On some legacy/FE targets, logread is not used and the -C shared ring buffer
        does not exist in userspace. In those cases, scanning the full dump for a shbuf header
        is slow and can false-positive.

        Returns True when we should skip RAM buffer parsing and proceed with file-based logs only.
        """
        try:
            task = UTaskLib(self.ramdump).get_utask_info("syslogd")
        except ProcessNotFoundExcetion:
            return True
        mmu = getattr(task, "mmu", None)
        vmas = getattr(task, "vmalist", None)
        if not mmu or not vmas:
            return True
        expected = self.DEFAULT_C_BYTES + 8
        for v in vmas:
            try:
                start = int(v.vm_start)
                end = int(v.vm_end)
                length = end - start
                if length < self.MIN_BUF:
                    continue
                try:
                    if (v.flags & 0b11) != 0b11:  # RW
                        continue
                except Exception:
                    pass
                if abs(length - expected) <= (64 * 1024):
                    return False
            except Exception:
                continue
        return True

    def _find_shbuf_via_syslogd(self):
        try:
            task = UTaskLib(self.ramdump).get_utask_info("syslogd")
        except ProcessNotFoundExcetion:
            return None

        mmu = getattr(task, "mmu", None)
        vmas = getattr(task, "vmalist", None)
        if not mmu or not vmas:
            return None

        candidates = []
        for v in vmas:
            try:
                start = int(v.vm_start)
                end = int(v.vm_end)
                length = end - start
                if length < self.MIN_BUF:
                    continue
                try:
                    if (v.flags & 0b11) != 0b11:
                        continue
                except Exception:
                    pass
                score = abs(length - (self.DEFAULT_C_BYTES + 8))
                candidates.append((score, start, length))
            except Exception:
                continue

        candidates.sort(key=lambda x: x[0])

        for _, base, length in candidates[:300]:
            hdr = UTaskLib.read_binary(self.ramdump, mmu, base, 8)
            if not hdr or len(hdr) < 8:
                continue
            size, tail = struct.unpack("<II", hdr)
            if not self._valid_hdr(size, tail, length - 8):
                continue
            sample = UTaskLib.read_binary(self.ramdump, mmu, base + 8, min(size, self.SAMPLE))
            if self._looks_like_logs(sample):
                return ("VA", base, size, tail, mmu)

        return None

    def _valid_hdr(self, size, tail, payload_max):
        if size < self.MIN_BUF or size > self.MAX_BUF:
            return False
        if payload_max is not None and size > payload_max:
            return False
        if tail < 0 or tail >= size:
            return False
        return True

    def _find_shbuf_phys(self):
        approx = self.DEFAULT_C_BYTES
        candidate_sizes = [approx, approx - 1, approx - 8, approx + 1, approx + 8]
        signatures = [struct.pack("<I", s & 0xffffffff) for s in candidate_sizes if s > 0]

        for start, end in self._phys_ranges():
            p = start
            while p < end:
                chunk = min(self.SCAN_CHUNK, end - p)
                buf = self.ramdump.read_physical(p, chunk)
                if not buf:
                    p += chunk
                    continue

                for sig in signatures:
                    idx = 0
                    while True:
                        pos = buf.find(sig, idx)
                        if pos < 0:
                            break
                        cand = p + pos
                        hdr = self.ramdump.read_physical(cand, 8)
                        if hdr and len(hdr) >= 8:
                            size, tail = struct.unpack("<II", hdr)
                            if self._valid_hdr(size, tail, None):
                                sample = self.ramdump.read_physical(cand + 8, min(size, self.SAMPLE))
                                if self._looks_like_logs(sample):
                                    return (cand, size, tail)
                        idx = pos + 4

                p += chunk

        return None

    def _phys_ranges(self):
        fields = ("ebi_files", "ram_files", "ramfiles", "mem_files", "files")
        for attr in fields:
            if hasattr(self.ramdump, attr):
                obj = getattr(self.ramdump, attr)
                try:
                    for e in obj:
                        if isinstance(e, (list, tuple)) and len(e) >= 3:
                            ints = [x for x in e if isinstance(x, int)]
                            if len(ints) >= 2:
                                s, t = ints[0], ints[1]
                                if s < t:
                                    yield (s, t)
                except Exception:
                    continue

    def _looks_like_logs(self, sample):
        if not sample or b"\0" not in sample:
            return False

        parts = sample.split(b"\0")
        good = 0
        total = 0
        for p in parts:
            if not p:
                continue
            total += 1
            s = p[:200]
            printable = sum((c in (9, 10, 13) or 32 <= c <= 126) for c in s)
            if len(s) > 0 and printable >= 0.70 * len(s):
                good += 1
            if total >= 50:
                break

        return good >= 3

    def _read_data(self, kind, mmu, base, size):
        if kind == "VA":
            return UTaskLib.read_binary(self.ramdump, mmu, base + 8, size)
        return self.ramdump.read_physical(base + 8, size)

    def _reconstruct(self, data, size, tail):
        msgs = []
        if not data or size <= 0 or tail < 0 or tail >= size:
            return msgs

        def find_nul(buf, start, end):
            i = buf.find(b"\0", start, end)
            return end if i < 0 else i

        cur = tail
        end = find_nul(data, cur, size)
        cur = end
        if cur >= size:
            cur2 = find_nul(data, 0, min(tail, size))
            if cur2 == tail:
                return msgs
            cur = cur2

        cur += 1
        if cur >= size:
            cur = 0

        max_iterations = size * 2  # Safety limit
        iteration_count = 0
        while cur != tail and iteration_count < max_iterations:
            end = find_nul(data, cur, size)
            if end == cur:
                cur += 1
                if cur >= size:
                    cur = 0
                iteration_count += 1
                continue
            msgs.append(data[cur:end])
            cur = end + 1
            if cur >= size:
                cur = 0
            iteration_count += 1

        if iteration_count >= max_iterations:
            print_out_str("Warning: circular buffer reconstruction hit iteration limit")

        return msgs

    def _write_msgs(self, outpath, msgs):
        """Write reconstructed messages as lines, UTF-8 safe."""
        with open(outpath, "wb") as f:
            for m in msgs:
                if not m:
                    continue
                try:
                    s = m.decode("utf-8", "replace")
                    b = s.encode("utf-8", "backslashreplace")
                except Exception:
                    b = repr(m).encode("utf-8", "backslashreplace")
                if not b.endswith(b"\n"):
                    b += b"\n"
                f.write(b)

    # =====================================================================
    # PART 2: File-based syslog (/var/log/messages or /log/messages + rotations)
    # =====================================================================
    def _extract_syslog_file(self, outdir):
        print_out_str("=== File-based extraction ===")

        ut = UTaskLib(self.ramdump)
        task = None

        # Find syslogd / rsyslogd
        try:
            task = ut.get_utask_info("syslogd")
            print_out_str("Using syslogd process for file-based syslog")
        except ProcessNotFoundExcetion:
            try:
                task = ut.get_utask_info("rsyslogd")
                print_out_str("Using rsyslogd process for file-based syslog")
            except ProcessNotFoundExcetion:
                print_out_str("No syslogd or rsyslogd found; skipping file-based extraction")
                return

        files = self.ramdump.read_structure_field(task.task_addr, 'struct task_struct', 'files')
        if not files:
            print_out_str("files_struct empty; skipping file-based syslog")
            return

        fdt = self.ramdump.read_structure_field(files, 'struct files_struct', 'fdt')
        max_fds = self.ramdump.read_structure_field(fdt, 'struct fdtable', 'max_fds')
        fd_array_ptr = self.ramdump.read_structure_field(fdt, 'struct fdtable', 'fd')

        addr_size = 8 if self.ramdump.arm64 else 4
        target_paths = ["/var/log/messages", "/log/messages"]
        found_fp = None
        found_path = None

        for idx in range(max_fds):
            fp = self.ramdump.read_word(fd_array_ptr + idx * addr_size)
            if not fp:
                continue
            try:
                path = self._get_path(fp)
            except Exception:
                continue

            if path in target_paths:
                print_out_str("File-based syslog FOUND: FD=%d, path=%s" % (idx, path))
                found_fp = fp
                found_path = path
                break

        if not found_fp:
            print_out_str("File-based syslog NOT FOUND in FD table")
            return

        # Dump main file
        main_out = os.path.join(outdir, "messages_file.txt")
        self._dump_file_inode_from_fileptr(found_fp, main_out)

        # Scan parent directory for rotated logs (messages.*, syslog.*)
        rotated_files = self._scan_rotated_logs(found_fp, outdir)

    # ---------- Rotated logs: scan parent dentry and dump messages.* ----------
    def _scan_rotated_logs(self, file_ptr, outdir):
        """
        From the dentry of /var/log/messages or /log/messages, go to parent directory
        and iterate d_subdirs to find messages*, syslog* siblings.
        """
        rotated_outputs = []
        try:
            f_path_ofs = self.ramdump.field_offset('struct file', 'f_path')
            path_addr = file_ptr + f_path_ofs
            dentry = self.ramdump.read_structure_field(path_addr, 'struct path', 'dentry')
            if not dentry:
                return rotated_outputs

            d_parent_ofs = self.ramdump.field_offset('struct dentry', 'd_parent')
            parent = self.ramdump.read_word(dentry + d_parent_ofs)
            if not parent:
                return rotated_outputs

            d_subdirs_ofs = self.ramdump.field_offset('struct dentry', 'd_subdirs')
            head = parent + d_subdirs_ofs
            curr = self.ramdump.read_word(head)  # head->next

            d_child_ofs = self.ramdump.field_offset('struct dentry', 'd_child')
            d_inode_ofs = self.ramdump.field_offset('struct dentry', 'd_inode')

            # Name of the main file (messages or syslog) to avoid double-dump
            main_name = self._dname(dentry)

            count = 0
            max_entries = 5000

            while curr != head and count < max_entries:
                child = curr - d_child_ofs
                name = self._dname(child)

                # match messages* or syslog*
                if name and (name.startswith("messages") or name.startswith("syslog")):
                    if name != main_name:  # skip the main one we already dumped
                        inode = self.ramdump.read_word(child + d_inode_ofs)
                        if inode:
                            # Output name: messages_file.<suffix>.txt
                            suffix = name[len("messages"):].lstrip(".") if name.startswith("messages") else name
                            if suffix == "":
                                suffix = "0"
                            outname = "messages_file.%s.txt" % suffix
                            outpath = os.path.join(outdir, outname)
                            print_out_str("Rotated syslog FOUND: %s (inode=0x%x)" % (name, inode))
                            self._dump_inode_to_path(inode, outpath)
                            rotated_outputs.append((name, outpath))

                curr = self.ramdump.read_word(curr)  # next in d_subdirs
                count += 1

            # sort rotated outputs by rotation index (messages.0, messages.1, ...)
            def rot_key(item):
                n = item[0]
                if n == "messages":
                    return 0
                if n.startswith("messages."):
                    try:
                        return int(n.split(".", 1)[1])
                    except Exception:
                        return 9999
                # syslog.*: place after messages.*
                if n == "syslog":
                    return 10000
                if n.startswith("syslog."):
                    try:
                        return 10000 + int(n.split(".", 1)[1])
                    except Exception:
                        return 19999
                return 29999

            rotated_outputs.sort(key=rot_key)
        except Exception as e:
            print_out_str("Error scanning rotated logs: %s" % e)

        return rotated_outputs

    # ---------- Dump inode to a given path ----------
    def _dump_inode_to_path(self, inode, outpath):
        """Dump a file's page-cache contents using xarray (>=5.x) or radix-tree (<=4.x)."""
        try:
            i_mapping_ofs = self.ramdump.field_offset('struct inode', 'i_mapping')
            i_size_ofs = self.ramdump.field_offset('struct inode', 'i_size')
            mapping = self.ramdump.read_word(inode + i_mapping_ofs)
            size = self.ramdump.read_u64(inode + i_size_ofs)

            if not mapping:
                print_out_str("inode->i_mapping NULL for %s" % outpath)
                return
            if size == 0:
                print_out_str("inode size=0 for %s" % outpath)
                return


            # ---- Debug: page-cache visibility for this inode ----
            try:
                nrpages_ofs = self.ramdump.field_offset('struct address_space', 'nrpages')
                nrpages = self.ramdump.read_word(mapping + nrpages_ofs)
            except Exception:
                nrpages = None

            try:
                base_small = self.ramdump.get_config_val('CONFIG_BASE_SMALL')
            except Exception:
                base_small = None

            # Print once per inode dump
            # print_out_str("[syslog-file] kernel=%s CONFIG_BASE_SMALL=%s mapping=0x%x size=%d nrpages=%s" %(str(self.ramdump.kernel_version), str(base_small), mapping, size, str(nrpages)))

            pages = (size + 4095) // 4096
            found = 0
            missing = 0

            print_out_str("Dumping syslog file -> %s, size=%d bytes, pages=%d" % (outpath, size, pages))

            try:
                with open(outpath, "wb") as f:
                    for idx in range(pages):
                        page = self._page_lookup(mapping, idx)
                        if page:
                            found += 1
                            data = self._read_page(page)
                            # Trim final page to inode size.
                            if idx == pages - 1:
                                r = size % 4096
                                if r:
                                    data = data[:r]
                            f.write(data)
                        else:
                            missing += 1
                            # Keep legacy behavior (preserve offsets) by filling missing pages with NULs.
                            # But if *all* pages are missing (common when kernel uses radix-tree and
                            # we mistakenly try xarray, or vice-versa), we delete the output below.
                            blk = size % 4096 if (idx == pages - 1 and size % 4096) else 4096
                            f.write(b"\x00" * blk)

            except Exception as e:
                print_out_str("Error writing syslog file %s: %s" % (outpath, e))
                try:
                    os.remove(outpath)
                except Exception:
                    pass
                return

            # Debug when nothing is found: dump the root entry pointer (helps distinguish mismatch vs missing pages)
            try:
                root_ofs = None
                for fld in ('page_tree', 'i_pages'):
                    try:
                        root_ofs = self.ramdump.field_offset('struct address_space', fld)
                        break
                    except Exception:
                        continue
                if root_ofs is not None:
                    root_addr = mapping + root_ofs
                    if self.ramdump.kernel_version > (4, 20, 0):
                        head_ofs = self.ramdump.field_offset('struct xarray', 'xa_head')
                        root_entry = self.ramdump.read_word(root_addr + head_ofs)
                    else:
                        rnode_ofs = self.ramdump.field_offset('struct radix_tree_root', 'rnode')
                        root_entry = self.ramdump.read_word(root_addr + rnode_ofs)
                    print_out_str("[syslog-file] root_entry=0x%x" % (root_entry if root_entry else 0))
            except Exception:
                pass

            if found == 0:
                # Avoid producing a completely NUL file (misleading) when we could not walk the cache.
                try:
                    os.remove(outpath)
                except Exception:
                    pass
                print_out_str("No page-cache pages found for %s (likely xarray/radix-tree mismatch or pages not in dump)." % outpath)
            elif missing:
                print_out_str("Warning: %d/%d pages missing for %s (gaps filled with NULs)" % (missing, pages, outpath))

        except Exception as e:
            print_out_str("Error dumping inode %s: %s" % (hex(inode), e))

    def _dump_file_inode_from_fileptr(self, fp, outpath):
        f_inode_ofs = self.ramdump.field_offset('struct file', 'f_inode')
        inode = self.ramdump.read_word(fp + f_inode_ofs)
        if not inode:
            print_out_str("inode is NULL; cannot dump file-based syslog")
            return
        self._dump_inode_to_path(inode, outpath)

    # ---------- XArray + page reading ----------
    # ---------- Page-cache lookup: xarray (>=4.20/5.x) OR radix-tree (<=4.x) ----------

    def _page_lookup(self, aspace, idx):
        """Return struct page* for file offset 'idx' (page index) from address_space."""
        page = self._xarray_lookup(aspace, idx)
        if page:
            return page
        return self._radix_lookup(aspace, idx)

    def _xarray_lookup(self, aspace, idx):
        """Kernel >= 5.x (and some late 4.x) page-cache: address_space->i_pages is xarray."""
        try:
            i_pages_ofs = self.ramdump.field_offset('struct address_space', 'i_pages')
            xa_head_ofs = self.ramdump.field_offset('struct xarray', 'xa_head')
            shift_ofs = self.ramdump.field_offset('struct xa_node', 'shift')
            slots_ofs = self.ramdump.field_offset('struct xa_node', 'slots')

            head = aspace + i_pages_ofs + xa_head_ofs
            entry = self.ramdump.read_word(head)
            if not entry:
                return None

            ptr_size = 8 if self.ramdump.arm64 else 4

            # Internal nodes are tagged with 0b10 (value 2)
            while (entry & 3) == 2:
                node = entry - 2
                shift = self.ramdump.read_u8(node + shift_ofs)
                pos = (idx >> shift) & 0x3F
                slot = node + slots_ofs + pos * ptr_size
                entry = self.ramdump.read_word(slot)
                if not entry:
                    return None

            # A normal entry (struct page*) has low bits 0.
            if (entry & 3) == 0:
                return entry
            return None
        except Exception:
            return None


    # ---- Radix-tree helpers (aligned with parsers/irqstate.py) ----
    # Used ONLY for file-based page-cache walk on 4.x kernels.
    def _rt_shift_to_maxindex(self, shift):
        radix_tree_map_shift = 6
        try:
            if int(self.ramdump.get_config_val("CONFIG_BASE_SMALL")) == 1:
                radix_tree_map_shift = 4
        except Exception:
            pass
        radix_tree_map_size = 1 << radix_tree_map_shift
        return (radix_tree_map_size << shift) - 1

    def _rt_is_internal_node(self, addr):
        radix_tree_entry_mask = 0x3
        if self.ramdump.kernel_version > (4, 20, 0):
            radix_tree_internal_node = 0x2
        else:
            radix_tree_internal_node = 0x1
        return (addr & radix_tree_entry_mask) == radix_tree_internal_node

    def _rt_entry_to_node(self, addr):
        if self.ramdump.kernel_version > (4, 20, 0):
            return addr & 0xfffffffffffffffd
        else:
            return addr & 0xfffffffffffffffe

    def _rt_lookup_v2(self, root_addr, index):
        """Lookup an element from radix-tree/xarray root (irqstate.py style).

        For our use-case (page-cache):
          * <=4.20: radix_tree_root/radix_tree_node (internal tag 0x1)
          * >4.20:  xarray/xa_node (internal tag 0x2)

        Returns the entry value (typically struct page* for page-cache).
        """
        rd = self.ramdump
        if rd.kernel_version > (4, 20, 0):
            rnode_offset       = rd.field_offset('struct xarray', 'xa_head')
            rnode_shift_offset = rd.field_offset('struct xa_node', 'shift')
            slots_offset       = rd.field_offset('struct xa_node', 'slots')
            pointer_size       = rd.sizeof('struct xa_node *')
        else:
            rnode_offset       = rd.field_offset('struct radix_tree_root', 'rnode')
            rnode_shift_offset = rd.field_offset('struct radix_tree_node', 'shift')
            slots_offset       = rd.field_offset('struct radix_tree_node', 'slots')
            pointer_size       = rd.sizeof('struct radix_tree_node *')

        radix_tree_map_mask  = 0x3f
        try:
            if int(rd.get_config_val("CONFIG_BASE_SMALL")) == 1:
                radix_tree_map_mask = 0xf
        except Exception:
            pass

        rnode_addr = rd.read_word(root_addr + rnode_offset)
        if self._rt_is_internal_node(rnode_addr):
            node_addr = self._rt_entry_to_node(rnode_addr)
            shift = rd.read_byte(node_addr + rnode_shift_offset)
            maxindex = self._rt_shift_to_maxindex(shift)
            if index > maxindex:
                return None

        while self._rt_is_internal_node(rnode_addr):
            parent_addr = self._rt_entry_to_node(rnode_addr)
            parent_shift = rd.read_byte(parent_addr + rnode_shift_offset)
            offset = (index >> parent_shift) & radix_tree_map_mask
            rnode_addr = rd.read_word(parent_addr + slots_offset + (offset * pointer_size))
            if rnode_addr == 0:
                return None
        return rnode_addr
    def _radix_lookup(self, aspace, idx):
        """Kernel <= 4.x page-cache lookup using irqstate.py-style radix walk."""
        try:
            root_ofs = None
            for fld in ('page_tree', 'i_pages'):
                try:
                    root_ofs = self.ramdump.field_offset('struct address_space', fld)
                    break
                except Exception:
                    continue
            if root_ofs is None:
                return None

            root_addr = aspace + root_ofs
            entry = self._rt_lookup_v2(root_addr, idx)
            if not entry:
                return None

            if self.ramdump.kernel_version <= (4, 20, 0):
                return entry & 0xfffffffffffffffe
            return entry
        except Exception:
            return None

    def _read_page(self, page):
        pfn = mm.page_to_pfn(self.ramdump, page)
        phys = pfn << self.ramdump.page_shift
        return self.ramdump.read_physical(phys, 4096)

    # ---------- Path / dentry helpers ----------

    def _get_path(self, fp):
        f_path_ofs = self.ramdump.field_offset('struct file', 'f_path')
        path_addr = fp + f_path_ofs

        dentry = self.ramdump.read_structure_field(path_addr, 'struct path', 'dentry')
        if not dentry:
            return ""

        parent_ofs = self.ramdump.field_offset('struct dentry', 'd_parent')
        names = []
        cur = dentry

        for _ in range(50):
            name = self._dname(cur)
            if not name or name == "/":
                break
            names.append(name)
            nxt = self.ramdump.read_word(cur + parent_ofs)
            if nxt == cur:
                break
            cur = nxt

        names.reverse()
        return "/" + "/".join(names)

    def _dname(self, dentry):
        d_name = self.ramdump.field_offset('struct dentry', 'd_name')
        name_ofs = self.ramdump.field_offset('struct qstr', 'name')
        len_ofs = self.ramdump.field_offset('struct qstr', 'len')

        q = dentry + d_name
        length = self.ramdump.read_u32(q + len_ofs)
        ptr = self.ramdump.read_word(q + name_ofs)
        length = min(length, 256)
        return cleanupString(self.ramdump.read_cstring(ptr, length))
