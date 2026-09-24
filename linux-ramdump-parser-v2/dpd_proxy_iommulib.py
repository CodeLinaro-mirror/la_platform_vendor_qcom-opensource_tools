# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: GPL-2.0-only
# Ramdump parser support for the qcom_dpd_proxy_iommu driver.
#
# The DPD (Dynamic Page Descriptor) proxy IOMMU driver does NOT maintain
# hardware page tables in the traditional sense.  Instead it keeps a
# software-side maple tree (struct dpd_smmu_domain.mappings) that maps
# IOVA ranges to struct dpd_mapping objects.  Each dpd_mapping holds a
# pointer to a struct dpd_scatterlist whose embedded sg_table carries the
# actual physical addresses.  The IOMMU hardware is programmed by the TEE
# (via SMCInvoke / ISecureMemoryManager service calls), so there are no
# TTBR/page-table registers to walk from HLOS.
#
# This module:
#   1. Locates every dpd_smmu_domain in the ramdump by walking the global
#      device list and matching the iommu_device ops pointer against the
#      address of dpd_smmu_ops (requires the module's .ko.unstripped).
#   2. Walks the per-domain maple tree to collect every dpd_mapping.
#   3. For each mapping resolves the physical address(es) from the
#      embedded sg_table using mm.page_to_pfn_vmemmap / get_vmemmap.
#   4. Emits output in the same columnar format used by parse_aarch64_tables
#      in aarch64iommulib.py so that all IOMMU output is consistent.

from print_out import print_out_str
from maple_tree import MapleTreeWalker
import linux_list as llist
import mm

# IOMMU protection flags (linux/iommu.h)
IOMMU_READ   = (1 << 0)
IOMMU_WRITE  = (1 << 1)
IOMMU_NOEXEC = (1 << 2)
IOMMU_MMIO   = (1 << 4)

# scatterlist page_link flag bits
SG_CHAIN = 0x01
SG_END   = 0x02


# Data classes
"""One contiguous physical segment within a dpd_mapping."""
class DpdProxySegment(object):
    def __init__(self, phys, length):
        self.phys  = phys
        self.length = length


"""One IOVA→PA mapping stored in a dpd_smmu_domain.mappings maple tree."""
class DpdProxyMapping(object):
    def __init__(self, iova, size, prot, segments):
        self.iova     = iova
        self.size     = size
        self.prot     = prot
        self.segments = segments


"""One dpd_smmu_domain extracted from the ramdump."""
class DpdProxyDomain(object):
    def __init__(self, domain_ptr, smmu_domain_ptr, client_name,
                 si_domain_id, attached):
        self.domain_ptr      = domain_ptr
        self.smmu_domain_ptr = smmu_domain_ptr
        self.client_name     = client_name
        self.si_domain_id    = si_domain_id
        self.attached        = attached
        self.mappings        = []


# Physical-address helpers
"""
    Convert a virtual struct page * to a physical address.

    Uses mm.get_vmemmap() + mm.page_to_pfn_vmemmap() which already handles
    all kernel-version differences (flat/sparse/vmemmap memory models).
"""
def _page_to_phys(ramdump, page_ptr):
    if not page_ptr:
        return None
    try:
        vmemmap = mm.get_vmemmap(ramdump)
        pfn = mm.page_to_pfn_vmemmap(ramdump, page_ptr, vmemmap)
        return pfn << ramdump.page_shift
    except Exception as e:
        print_out_str("DPD proxy IOMMU: page_to_phys failed for page=0x%x: %s"
                      % (page_ptr, e))
        return None


"""
    Return the physical address of the memory described by a scatterlist entry.

    sg_phys(sg) = page_to_phys(sg_page(sg)) + sg->offset
    sg_page(sg) = (struct page *)(sg->page_link & ~SG_CHAIN & ~SG_END)
"""
def _sg_phys(ramdump, sg_ptr):
    page_link = ramdump.read_structure_field(
        sg_ptr, 'struct scatterlist', 'page_link')
    offset = ramdump.read_structure_field(
        sg_ptr, 'struct scatterlist', 'offset')

    if page_link is None or offset is None:
        return None

    page_ptr = page_link & ~(SG_CHAIN | SG_END)
    if not page_ptr:
        return None

    phys = _page_to_phys(ramdump, page_ptr)
    if phys is None:
        return None

    return phys + offset


"""
    Walk the sg_table embedded in a dpd_scatterlist and return a list of
    DpdProxySegment objects (one per scatterlist entry).
"""
def _walk_sgtable(ramdump, dpd_sg_ptr):
    segments = []

    sgt_offset = ramdump.field_offset('struct dpd_scatterlist', 'sgt')
    if sgt_offset is None:
        print_out_str("DPD proxy IOMMU: field 'sgt' not found in "
                      "struct dpd_scatterlist")
        return segments

    sgt_ptr = dpd_sg_ptr + sgt_offset

    sgl = ramdump.read_structure_field(sgt_ptr, 'struct sg_table', 'sgl')
    orig_nents = ramdump.read_structure_field(
        sgt_ptr, 'struct sg_table', 'orig_nents')

    if not sgl or not orig_nents:
        return segments

    sg_size = ramdump.sizeof('struct scatterlist')
    if not sg_size:
        return segments

    sg = sgl
    entries_seen = 0

    while entries_seen < orig_nents:
        if not sg:
            break

        page_link = ramdump.read_structure_field(
            sg, 'struct scatterlist', 'page_link')
        if page_link is None:
            break

        # Follow chain pointer to the next scatterlist array
        if page_link & SG_CHAIN:
            sg = page_link & ~(SG_CHAIN | SG_END)
            if not sg:
                break
            # Re-read page_link for the first entry of the new array
            page_link = ramdump.read_structure_field(
                sg, 'struct scatterlist', 'page_link')
            if page_link is None:
                break

        length = ramdump.read_structure_field(
            sg, 'struct scatterlist', 'length')
        if length is None:
            break

        phys = _sg_phys(ramdump, sg)
        if phys is not None and length > 0:
            segments.append(DpdProxySegment(phys, length))

        entries_seen += 1

        # End of list?
        if page_link & SG_END:
            break

        sg += sg_size

    return segments


# Maple-tree callback
"""
    Callable passed to MapleTreeWalker.walk().

    The walker calls __call__(entry) for every non-empty leaf slot.
    Each entry is a raw pointer to struct dpd_mapping.
"""
class _MappingCollector(object):
    def __init__(self, ramdump):
        self.ramdump  = ramdump
        self.mappings = []

    def __call__(self, entry, *args):
        if not entry:
            return

        rd = self.ramdump
        dpd_mapping_ptr = entry

        iova = rd.read_structure_field(
            dpd_mapping_ptr, 'struct dpd_mapping', 'iova')
        prot = rd.read_structure_field(
            dpd_mapping_ptr, 'struct dpd_mapping', 'prot')
        dpd_sg_ptr = rd.read_structure_field(
            dpd_mapping_ptr, 'struct dpd_mapping', 'dpd_sg')

        if iova is None or dpd_sg_ptr is None:
            return

        size = rd.read_structure_field(
            dpd_sg_ptr, 'struct dpd_scatterlist', 'size')
        if size is None:
            size = 0

        segments = _walk_sgtable(rd, dpd_sg_ptr)

        self.mappings.append(DpdProxyMapping(iova, size, prot or 0, segments))


"""Walk the dpd_smmu_domain.mappings maple tree and populate domain.mappings."""
def _collect_mappings(ramdump, domain, smmu_domain_ptr):
    mappings_offset = ramdump.field_offset(
        'struct dpd_smmu_domain', 'mappings')
    if mappings_offset is None:
        print_out_str(
            "DPD proxy IOMMU: field 'mappings' not found in "
            "struct dpd_smmu_domain")
        return

    mappings_mt_ptr = smmu_domain_ptr + mappings_offset

    collector = _MappingCollector(ramdump)
    try:
        walker = MapleTreeWalker(ramdump)
        walker.walk(mappings_mt_ptr, collector)
    except Exception as e:
        print_out_str(
            "DPD proxy IOMMU: maple tree walk failed for domain %s: %s"
            % (domain.client_name, e))
        return

    domain.mappings = sorted(collector.mappings, key=lambda m: m.iova)


# Output
"""Convert IOMMU_READ/WRITE flags to a human-readable bracket string."""
def _prot_to_str(prot):
    has_r = bool(prot & IOMMU_READ)
    has_w = bool(prot & IOMMU_WRITE)
    if has_r and has_w:
        return '[R/W]'
    elif has_r:
        return '[RO]'
    elif has_w:
        return '[WO]'
    else:
        return '[--]'


"""
    Write one output file per DPD proxy domain, using the same column layout
    as parse_aarch64_tables() in aarch64iommulib.py:

"""
def parse_dpd_proxy_tables(ramdump, domain, domain_num):
    device_name = ramdump.win_safe_name_for_path(
        (domain.client_name or 'unknown').strip())
    if not device_name:
        device_name = 'unknown'

    fname = ('smmu_info/dpd_proxy_%s_%02d_domain_%s.txt'
             % (device_name, domain_num,
                str(domain.si_domain_id) if domain.si_domain_id is not None
                else 'NA'))

    with ramdump.open_file(fname, 'w') as out:
        out.write('DPD Proxy IOMMU Domain\n')
        out.write('======================\n')
        out.write('Client      : %s\n' % domain.client_name)
        out.write('SI Domain ID: %s\n'
                  % (str(domain.si_domain_id)
                     if domain.si_domain_id is not None else 'N/A'))
        out.write('Attached    : %s\n' % ('Yes' if domain.attached else 'No'))
        out.write('\n')

        out.write(
            '[VA Start -- VA End  ] [Size      ] '
            '[PA Start   -- PA End  ] [Attributes]'
            '[Page Table Entry Size] [Memory Type] '
            '[Shareability] [Non-Executable]\n')

        if not domain.mappings:
            out.write('No mappings found.\n')
            return

        for mapping in domain.mappings:
            iova_start = mapping.iova
            iova_end   = iova_start + mapping.size - 1
            prot_str   = _prot_to_str(mapping.prot)

            if not mapping.segments:
                out.write(
                    '0x%x--0x%x [0x%x] [UNMAPPED - sg_table empty or '
                    'unresolvable]\n'
                    % (iova_start, iova_end, mapping.size))
                continue

            iova_cursor = iova_start
            for seg in mapping.segments:
                seg_iova_end = iova_cursor + seg.length - 1
                phys_end     = seg.phys + seg.length - 1

                out.write(
                    '0x%x--0x%x [0x%x] A:0x%x--0x%x [0x%x] '
                    '%s[4K] [N/A] [N/A] [N/A]\n'
                    % (iova_cursor, seg_iova_end, seg.length,
                       seg.phys, phys_end, seg.length,
                       prot_str))

                iova_cursor += seg.length

