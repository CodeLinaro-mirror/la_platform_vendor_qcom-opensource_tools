# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: GPL-2.0-only

import bisect
from print_out import print_out_str

def parse_vmcoreinfo(elf):
    vmcoreinfo = {}
    for segment in elf.iter_segments():
        if segment['p_type'] == 'PT_NOTE':
            for note in segment.iter_notes():
                if note['n_name'] == 'VMCOREINFO':
                    try:
                        text = note['n_desc'].decode('utf-8', errors='ignore')
                        for line in text.strip().split('\n'):
                            if '=' in line:
                                key, value = line.split('=', 1)
                                vmcoreinfo[key.strip()] = value.strip()
                    except Exception as e:
                        print_out_str(f"Failed to parse VMCOREINFO: {e}")
    return vmcoreinfo

def load_segments(elf):
    segments = []
    for segment in elf.iter_segments():
        if segment['p_type'] == 'PT_LOAD':
            segments.append({
                'vaddr': segment['p_vaddr'],
                'paddr': segment['p_paddr'],
                'offset': segment['p_offset'],
                'filesz': segment['p_filesz'],
                'memsz': segment['p_memsz'],
                'flags': segment['p_flags']
            })
    return segments

def read_physical_vmcore(ebi_files_vmcoredump, vmcore_file, paddr, length):
    if paddr is None or length <= 0:
        return None
    result = bytearray()
    remaining = length
    current_paddr = paddr
    seg_starts = [seg[0] for seg in ebi_files_vmcoredump]
    while remaining > 0:
        idx = bisect.bisect_right(seg_starts, current_paddr) - 1
        if idx < 0 or idx >= len(ebi_files_vmcoredump):
            break
        pa, end_addr, va, size, seg_offset = ebi_files_vmcoredump[idx]
        if not (pa <= current_paddr <= end_addr):
            break
        offset_in_seg = current_paddr - pa
        available = end_addr - current_paddr + 1
        read_len = min(remaining, available)
        file_offset = seg_offset + offset_in_seg
        try:
            vmcore_file.seek(file_offset)
            data = vmcore_file.read(read_len)
            if not data:
                break
            result.extend(data)
            remaining -= len(data)
            current_paddr += len(data)
        except Exception:
            break
    return bytes(result) if result else None
