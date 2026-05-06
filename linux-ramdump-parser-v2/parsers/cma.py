#Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
#SPDX-License-Identifier: GPL-2.0-only

from parser_util import register_parser, RamParser
from print_out import print_out_str
from mm import get_vmemmap, page_buddy
from .pagetracking import PageTrace

@register_parser('--print-cma-areas', 'Print cma memory region info ')
class CmaAreas(RamParser):
    def __init__(self, *args):
        super(CmaAreas, self).__init__(*args)
        self.offset_comm = self.ramdump.field_offset('struct page_owner', 'comm')
        if self.ramdump.is_config_defined('CONFIG_PAGE_OWNER'):
            self.pagetrace = PageTrace(self.ramdump)

    def parse_pfn(self, ramdump, pfn, cma, op_file, dict):

        vmemmap = get_vmemmap(ramdump)
        page_size = ramdump.sizeof('struct page')
        page = vmemmap + pfn * page_size
        str = "{0} pfn : 0x{1:x} page : 0x{2:x} flag : 0x{3:x} mapping : 0x{" \
              "4:x} count : {5} _mapcount : {6:x}  PID : {7}{8} {9}\n ts_nsec      {10:>32d} \n free_ts_nsec {11:>32d} \n{12}\n"
        str1 = "{0} pfn : 0x{1:x}--0x{2:x} head_page : 0x{3:x} flag : {4:x} " \
               "mapping : 0x{5:x} count : {6} _mapcount : {7:x} {8}\n{9}\n"
        str2 = "{0} pfn : 0x{1:x} pge : 0x{2:x} count : {3} _mapcount : " \
               "{4:x} {5}\n"
        str3 = "{0} pfn : 0x{1:x}--0x{2:x} head_page : 0x{3:x} count : {4} " \
               "_mapcount : {5:x}  {6}\n"
        page_flags = ramdump.read_structure_field(page, 'struct page', 'flags')
        tail_page = ramdump.read_structure_field(
            page, 'struct page', 'compound_head')
        if (tail_page & 1) == 1:
            page = tail_page - 1
        nr_pages = 1
        page_count = ramdump.read_structure_field(
            page, 'struct page', '_refcount.counter')
        mapcount_offset = ramdump.field_offset('struct page', '_mapcount')
        page_mapcount = ramdump.read_int(page + mapcount_offset)

        if page_mapcount == 0xffffffff:
            page_mapcount = -1
        page_mapping = ramdump.read_structure_field(page, 'struct page', 'mapping')
        is_pinned_str = ""
        if (page_mapcount >= 0) and ((page_count - page_mapcount) >= 2):
            is_pinned_str = "<===pinned"
        if cma == 1:
            cma_usage = "[devm]"
        else:
            cma_usage = "[ncma]"
            # test if buddy
            if page_mapcount == 0xffffff80:
                cma_usage = "[budd]"
                nr_pages = ramdump.read_structure_field(
                    page, 'struct page', 'private')
                nr_pages = 1 << nr_pages
            elif page_mapping != 0:
                anon_page = page_mapping & 0x1
                if anon_page != 0:
                    cma_usage = "[anon]"
                else:
                    cma_usage = "[file]"
            else:
                cma_usage = "[unkw]"

        if ramdump.is_config_defined('CONFIG_PAGE_OWNER'):
            if (page_buddy(ramdump, page)) or page_count == 0:
                function_list = ""
                pid = -1
                ts_nsec = -1
                free_ts_nsec = -1
                comm = -1
            else:
                function_list, order, pid, ts_nsec, gfp, comm, ext_flags = self.pagetrace.page_trace(pfn, True)
                free_ts_nsec = 0
                if pid in dict:
                    dict[pid] = dict[pid] + 1
                else:
                    dict[pid] = 1
            if nr_pages == 1:
                op_file.write(str.format(
                    cma_usage, pfn, page, page_flags, page_mapping, page_count,
                    page_mapcount, pid, " comm: {}".format(comm) if self.offset_comm is not None else "", \
                    is_pinned_str, ts_nsec, free_ts_nsec, function_list))
            else:
                op_file.write(str1.format(cma_usage, pfn, pfn + nr_pages - 1,
                                          page, page_flags, page_mapping,
                                          page_count, page_mapcount,
                                          is_pinned_str, function_list))
        else:
            if nr_pages == 1:
                op_file.write(str2.format(cma_usage, pfn, page, page_count,
                                          page_mapcount, is_pinned_str))
            else:
                op_file.write(str3.format(
                    cma_usage, pfn, pfn + nr_pages - 1, page, page_count,
                    page_mapcount, is_pinned_str))
        return nr_pages

    def cma_region_dump(self, ramdump, cma, cma_name):
        # Support both single-range and multi-range CMA structures.
        nranges_off = ramdump.field_offset('struct cma', 'nranges')
        ranges_off = ramdump.field_offset('struct cma', 'ranges')
        if nranges_off is not None and ranges_off is not None:
            try:
                nranges = ramdump.read_int(cma + nranges_off)
            except Exception:
                nranges = 0
            size_of_memrange = ramdump.sizeof('struct cma_memrange')
            for r in range(0, nranges if nranges > 0 else 1):
                range_addr = cma + ranges_off + r * size_of_memrange
                try:
                    base_pfn = ramdump.read_structure_field(range_addr, 'struct cma_memrange', 'base_pfn')
                    cma_count = ramdump.read_structure_field(range_addr, 'struct cma_memrange', 'count')
                    try:
                        bitmap = ramdump.read_structure_field(range_addr, 'struct cma_memrange', 'bitmap')
                    except Exception:
                        bitmap = 0
                except Exception:
                    continue
                self._dump_cma_range(ramdump, base_pfn, cma_count, bitmap, "%s[%d]" % (cma_name, r))
            return

        # legacy single-range layout
        base_pfn = ramdump.read_structure_field(
            cma, 'struct cma', 'base_pfn')
        cma_count = ramdump.read_structure_field(
            cma, 'struct cma', 'count')
        bitmap = ramdump.read_structure_field(
            cma, 'struct cma', 'bitmap')
        self._dump_cma_range(ramdump, base_pfn, cma_count, bitmap, cma_name)

    def _dump_cma_range(self, ramdump, base_pfn, cma_count, bitmap, cma_name):
        # Coerce possible None values to ints to avoid formatting errors
        base_pfn = int(base_pfn or 0)
        cma_count = int(cma_count or 0)
        bitmap = int(bitmap or 0)
        bitmap_end = bitmap + cma_count // 8 if bitmap else 0
        in_system = 1
        end_pfn = base_pfn + cma_count
        name = "cma_report_" + cma_name + ".txt"
        op_file = ramdump.open_file(name)
        op_file.write("CMA report\n")
        op_file.write(" - name : {0}\n".format(cma_name))
        op_file.write(" - base_pfn\t\t\t\t: 0x{0:x}\n".format(base_pfn))
        op_file.write(" - end_pfn\t\t\t\t: 0x{0:x}\n".format(end_pfn))
        op_file.write(" - count\t\t\t\t: 0x{0:x}\n".format(cma_count))
        op_file.write(" - size\t\t\t\t\t: {0}KB\n".format(cma_count << 0x2))
        op_file.write(" - bitmap_start\t\t: 0x{0:x}\n".format(bitmap))
        op_file.write(" - bitmap_end\t\t: 0x{0:x}\n".format(bitmap_end))
        op_file.write(" - in_system\t\t: {0}\n\n".format(in_system))
        dict = {}
        byte_index = 0
        PFNS_PER_BYTE = 8
        COUNT_TO_BYTE = cma_count // PFNS_PER_BYTE
        lst = []
        while byte_index < COUNT_TO_BYTE:
            value = ramdump.read_byte(bitmap + byte_index) if bitmap else 0
            lst.append([bitmap + byte_index, value])
            pfn_index = 0
            while pfn_index < PFNS_PER_BYTE:
                pfn = base_pfn + byte_index * PFNS_PER_BYTE + pfn_index
                bit_value = (value >> pfn_index) & 0x1
                cma_flag = 1 if bit_value != 0 else 0
                if cma_flag == 1:
                    self.parse_pfn(ramdump, pfn, cma_flag, op_file, dict)
                pfn_index = pfn_index + 1
            byte_index = byte_index + 1

        sort_list = sorted(dict.items(), key=lambda kv: kv[1], reverse=True)
        for k, v in sort_list:
            print("PID %-8d alloc times %-8d" % (k, v), file=op_file)
        line_break = 0
        print("bitmap: " % (), file=op_file)
        for item in lst:
            print("%02x" % (item[1]), file=op_file, end="")
            line_break = line_break + 1
            if line_break == 16:
                print("%s" % (" "), file=op_file)
                line_break = 0
        op_file.close()

    def _get_page_shift(self, ramdump):
        if hasattr(ramdump, "page_shift") and ramdump.page_shift:
            return int(ramdump.page_shift)
        return 12

    def _iter_cma_ranges(self, ramdump, cma_addr):
        """Yield (range_idx, base_pfn, count_pages, bitmap_ptr) for each CMA range.
        Supports both legacy single-range and 6.18+ multi-range layouts.
        """
        # 6.18+ multi-range
        try:
            nranges_off = ramdump.field_offset('struct cma', 'nranges')
            ranges0_off = ramdump.field_offset('struct cma', 'ranges[0]')
            memrange_sz = ramdump.sizeof('struct cma_memrange')
            if nranges_off is not None and ranges0_off is not None and memrange_sz:
                nr = ramdump.read_s32(cma_addr + nranges_off) or 0
                nr = max(0, min(nr, 8))
                for i in range(nr):
                    raddr = cma_addr + ranges0_off + i * memrange_sz
                    base_pfn = ramdump.read_structure_field(raddr, 'struct cma_memrange', 'base_pfn') or 0
                    count = ramdump.read_structure_field(raddr, 'struct cma_memrange', 'count') or 0
                    # union: bitmap may not exist early; guard it
                    try:
                        bitmap = ramdump.read_structure_field(raddr, 'struct cma_memrange', 'bitmap') or 0
                    except Exception:
                        bitmap = 0
                    yield (i, int(base_pfn), int(count), int(bitmap))
                return
        except Exception:
            pass

        # legacy single-range
        base_pfn = ramdump.read_structure_field(cma_addr, 'struct cma', 'base_pfn') or 0
        count = ramdump.read_structure_field(cma_addr, 'struct cma', 'count') or 0
        bitmap = ramdump.read_structure_field(cma_addr, 'struct cma', 'bitmap') or 0
        yield (0, int(base_pfn), int(count), int(bitmap))

    def print_cma_areas(self, ramdump):
        output_file = ramdump.open_file("cma_report_simple.txt")
        cma_area_count = ramdump.read_u32('cma_area_count')
        cma_area_base_addr = ramdump.address_of('cma_areas')
        size_of_cma = ramdump.sizeof('struct cma')

        page_shift = self._get_page_shift(ramdump)
        page_kb = 1 << (page_shift - 10)

        hdr = "cma : 0x{0:x} ranges : {1} total : 0x{2:x} pages ({3}KB)\n"
        rng = "  range[{0}] base_pfn : 0x{1:x} size : 0x{2:x} pages ({3}KB)\n\n"
        name_fmt = "name : {0}\n\n"

        cma = [0] * cma_area_count
        cma_name = [None] * cma_area_count

        for idx in range(cma_area_count):
            cma_area = cma_area_base_addr + idx * size_of_cma

            # name (unchanged)
            if ramdump.kernel_version >= (5, 10, 0):
                name_addr_offset = ramdump.field_offset('struct cma', 'name')
                name_addr = cma_area + name_addr_offset
                name = ramdump.read_cstring(name_addr, 64)
            else:
                name_addr = ramdump.read_structure_field(cma_area, 'struct cma', 'name')
                name = ramdump.read_cstring(name_addr, 48)

            if not name:
                name = "unknown"
            elif name == "linux,cma":
                name = "dma_contiguous_default_area"

            # ranges summary (FIXED for 6.18)
            ranges = list(self._iter_cma_ranges(ramdump, cma_area))
            total_pages = sum(r[2] for r in ranges)
            output_file.write(hdr.format(int(cma_area), len(ranges), total_pages, total_pages * page_kb))
            output_file.write(name_fmt.format(name))
            for r_idx, base_pfn, count, _bitmap in ranges:
                output_file.write(rng.format(r_idx, base_pfn, count, count * page_kb))

            cma[idx] = cma_area
            cma_name[idx] = name

        output_file.close()

        # detailed per-area reports (unchanged)
        for idx in range(cma_area_count):
            self.cma_region_dump(ramdump, cma[idx], cma_name[idx])

    def parse(self):
        if self.ramdump.kernel_version < (4, 9):
            print_out_str("Linux version lower than 4.9 is not supported!!")
            return
        else:
            self.print_cma_areas(self.ramdump)