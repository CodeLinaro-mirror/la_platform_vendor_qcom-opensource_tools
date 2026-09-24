# Copyright (c) 2018-2020,2021 The Linux Foundation. All rights reserved.
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 and
# only version 2 as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

import os, re
from parser_util import register_parser, RamParser, cleanupString
from print_out import print_out_str
from utils.anomalies import Anomaly

class memory_area:
    def __init__(self, name, base, size):
        self.name = name
        self.base = base
        self.size = size

def print_tasklet_info(ramdump, core, tasklet):
    tasklet_vec_addr = ramdump.address_of(tasklet)
    tasklet_head = tasklet_vec_addr + ramdump.per_cpu_offset(core)
    tasklet_head = ramdump.read_word(tasklet_head)
    next_offset = ramdump.field_offset('struct tasklet_struct', 'next')
    func_offset = ramdump.field_offset('struct tasklet_struct', 'func')
    count_offset = ramdump.field_offset('struct tasklet_struct', 'count')
    if tasklet_head != 0x0:
        print_out_str("Pending Tasklet info for {0}:".format(tasklet))

    while (tasklet_head != 0x0):
        print_out_str("struct tasklet_struct: 0x{0:x}:".format(tasklet_head))
        tasklet_func_addr = ramdump.read_word(tasklet_head + func_offset)
        tasklet_func = ramdump.unwind_lookup(tasklet_func_addr)
        if tasklet_func is None:
            tasklet_func = "Dynamic module/symbol not found"
        else:
            tasklet_func = tasklet_func[0]
        print_out_str("\tfunc : 0x{:<16x} -> {}".format(tasklet_func_addr, tasklet_func))
        count = ramdump.read_int(tasklet_head + count_offset)
        if count != 0:
            print_out_str("\tcount: 0x{:<16x} -> this tasklet is disabled".format(count))
        else:
            print_out_str("\tcount: 0x{:<16x} -> this tasklet is enabled".format(count))
        tasklet_head = ramdump.read_word(tasklet_head + next_offset)


def parse_softirq_stat(ramdump):
    irq_stat_addr = ramdump.address_of('irq_stat')
    softirq_name_addr = ramdump.address_of('softirq_to_name')
    sizeof_softirq_name = ramdump.sizeof('softirq_to_name')
    sofrirq_name_arr_size = sizeof_softirq_name // ramdump.sizeof('char *')
    softirq_to_name_array =["HI", "TIMER", "NET_TX", "NET_RX", "BLOCK", "IRQ_POLL","TASKLET", "SCHED", "HRTIMER", "RCU"]
    no_of_cpus = ramdump.get_num_cpus()
    index = 0
    size_of_irq_stat = ramdump.sizeof('irq_cpustat_t')
    for index in ramdump.iter_cpus():
        if ramdump.kernel_version >= (4, 19):
            irq_stat = irq_stat_addr + ramdump.per_cpu_offset(index)
        else:
            irq_stat = irq_stat_addr + index*size_of_irq_stat
        softirq_pending = ramdump.read_structure_field(
                                irq_stat, 'irq_cpustat_t', '__softirq_pending')
        pending = ""
        pos = sofrirq_name_arr_size - 1
        while pos >= 0:
            if softirq_pending & (1 << pos):
                if ramdump.minidump:
                    flag = softirq_to_name_array[pos]
                else:
                    flag_addr = ramdump.read_word(ramdump.array_index(
                    softirq_name_addr, "char *", pos))
                    flag = ramdump.read_cstring(flag_addr, 48)
                pending += flag
                pending += " | "
            pos = pos - 1
        if pending == "":
            pending = "None"
        else:
            pending = pending.rstrip().rstrip("|")
        print_out_str("core {0} : __softirq_pending = {1}".format(
                                index, pending))
        if not ramdump.minidump:
            if "TASKLET" in pending or "HI" in pending:
                print_tasklet_info(ramdump, index, 'tasklet_vec')
                print_tasklet_info(ramdump, index, 'tasklet_hi_vec')

def check_qseecom_invalid_cmds(ramdump):
    invalid_qsecom_cmds_id = ["3", "5", "7", "9", "14", "15", "16", "17", "19", "23" , "29"]
    invalid_qsecom_cmds = []
    return_string = ""
    if os.path.exists(os.path.join(ramdump.outdir, "qsee_log.txt")):
        if os.stat(os.path.join(ramdump.outdir, "qsee_log.txt")).st_size:
            with open(os.path.join(ramdump.outdir, "qsee_log.txt"), "r+") as fd:
                for line in fd:
                    if re.search("TZ App cmd handler, cmd_id", line):
                        cmd_id = line.split()[-1]
                        if cmd_id in invalid_qsecom_cmds_id:
                            invalid_qsecom_cmds.append(cmd_id)
            if len(invalid_qsecom_cmds):
                return_string += "qsecomm sample app running invalid cmds : "
                for i in range(len(invalid_qsecom_cmds)):
                    return_string += invalid_qsecom_cmds[i] + " "
                return (return_string + "\n")
    return return_string

def do_parse_qsee_log(ramdump):
    qsee_out = ramdump.open_file('qsee_log.txt')
    g_qsee_log_addr = ramdump.address_of('g_qsee_log')
    g_qsee_log_v2_addr = ramdump.address_of('g_qsee_log_v2')
    tzdbg_addr = ramdump.address_of('tzdbg')
    is_enlarged_buf_addr = ramdump.field_offset('struct tzdbg', 'is_enlarged_buf')
    is_enlarged_buf = False
    if is_enlarged_buf_addr is not None:
        is_enlarged_buf = ramdump.read_bool(tzdbg_addr + is_enlarged_buf_addr)
    log_buf_offset = ramdump.field_offset('struct tzdbg_log_t', 'log_buf')
    qsee_log_buf_size = 0x8000 ##define QSEE_LOG_BUF_SIZE 0x8000
    if is_enlarged_buf is True:
        qsee_log_buf_size = 0x20000 ##define QSEE_LOG_BUF_SIZE_V2 0x20000
        g_qsee_log_addr = g_qsee_log_v2_addr
        log_buf_offset = ramdump.field_offset('struct tzdbg_log_v2_t', 'log_buf')
    if g_qsee_log_addr is None:
        print_out_str("!!! g_qsee_logs not found")
        qsee_out.close()
        return
    try:
        g_qsee_log_addr = ramdump.read_word(g_qsee_log_addr)
    except Exception as e:
        print_out_str('!!! Cannot read g_qsee_log_addr')
        qsee_out.close()
        return
    log_buf_addr = g_qsee_log_addr + log_buf_offset
    qsee_log_data = ramdump.read_cstring(log_buf_addr, qsee_log_buf_size)
    qsee_log_data = qsee_log_data.rstrip(' \t\r\n\0')
    qsee_out.write(qsee_log_data)
    qsee_out.close()

@register_parser('--print-reserved-mem', 'Print reserved memory info ')
class ReservedMem(RamParser):
    def get_reserved_mem(self, ramdump, list_memory_area):
        if "reserved_mem *" in ramdump.type_of('reserved_mem'):
            reserved_mem_addr = ramdump.read_pointer('reserved_mem')
        else:
            reserved_mem_addr = ramdump.address_of('reserved_mem')
        reserved_mem_count_addr = ramdump.address_of_symbol_from_file('reserved_mem_count', 'of_reserved_mem.c')
        reserved_mem_count = ramdump.read_int(reserved_mem_count_addr)
        base_offset = ramdump.field_offset('struct reserved_mem', 'base')
        size_offset = ramdump.field_offset('struct reserved_mem', 'size')

        for i in range(0, reserved_mem_count):
            addr_index = ramdump.array_index(reserved_mem_addr, 'struct reserved_mem', i)
            name = ramdump.read_structure_cstring(addr_index, 'struct reserved_mem', 'name')
            if  ramdump.arm64:
                base = ramdump.read_u64(addr_index + base_offset)
                size = ramdump.read_word(addr_index + size_offset)
            else:
                base = ramdump.read_u32(addr_index + base_offset)
                size = ramdump.read_u32(addr_index + size_offset)
            memory_area_instance = memory_area(name, base, size)
            list_memory_area.append(memory_area_instance)

        list_memory_area.sort(key=lambda c: c.base)

    def get_kernel_resource(self, list_memory_area):
        mem_res_mem_addr = self.ramdump.address_of('mem_res')
        start_offset = self.ramdump.field_offset('struct resource', 'start')
        end_offset = self.ramdump.field_offset('struct resource', 'end')
        start = 0
        end = 0
        for i in range(0, 2):
            mem_res_mem_addr_index = self.ramdump.array_index(mem_res_mem_addr, 'struct resource', i)
            name = self.ramdump.read_structure_cstring(mem_res_mem_addr_index, 'struct resource', 'name')
            if self.ramdump.arm64:
                start = self.ramdump.read_u64(mem_res_mem_addr_index + start_offset)
                end = self.ramdump.read_u64(mem_res_mem_addr_index + end_offset)
            else:
                start = self.ramdump.read_u32(mem_res_mem_addr_index + start_offset)
                end = self.ramdump.read_u32(mem_res_mem_addr_index + end_offset)

            memory_area_instance = memory_area(name, start, end - start)
            list_memory_area.append(memory_area_instance)

    def get_cma_areas(self, ramdump, list_memory_area):
        base_pfn_offset = ramdump.field_offset('struct cma', 'base_pfn')
        if base_pfn_offset is None:
            base_pfn_offset = ramdump.field_offset('struct cma', 'ranges') + ramdump.field_offset('struct cma_memrange', 'base_pfn')
        cma_area_count = ramdump.read_u32('cma_area_count')
        cma_area_base_addr = ramdump.address_of('cma_areas')
        for cma_index in range(0, cma_area_count):
            cma_area = ramdump.array_index(cma_area_base_addr, 'struct cma', cma_index)
            base_pfn = ramdump.read_word(cma_area + base_pfn_offset)
            cma_size = ramdump.read_structure_field(
                cma_area, 'struct cma', 'count')
            if (ramdump.kernel_version >= (5, 10, 0)):
                name_addr_offset = ramdump.field_offset('struct cma', 'name')
                name_addr = (cma_area + name_addr_offset)
                name = ramdump.read_cstring(name_addr, 64)
            else:
                name_addr = ramdump.read_structure_field(cma_area, 'struct cma', 'name')
                name = ramdump.read_cstring(name_addr, 48)
            memory_area_instance = memory_area(name, base_pfn << ramdump.page_shift, cma_size << ramdump.page_shift)

            if any(x.base == memory_area_instance.base for x in list_memory_area) == False:
                list_memory_area.append(memory_area_instance)


    def get_memory_block(self, ramdump, list_memory_area):
        cnt = ramdump.read_structure_field('memblock', 'struct memblock', 'memory.cnt')
        total_size = ramdump.read_structure_field('memblock', 'struct memblock', 'memory.total_size')
        region = ramdump.read_structure_field('memblock', 'struct memblock', 'memory.regions')

        for i in range(cnt):
            start = ramdump.read_structure_field(region, 'struct memblock_region', 'base')
            size = ramdump.read_structure_field(region, 'struct memblock_region', 'size')
            memory_area_instance = memory_area("memory", start, size)
            if any(x.base == memory_area_instance.base for x in list_memory_area) == False:
                list_memory_area.append(memory_area_instance)

        cnt = ramdump.read_structure_field('memblock', 'struct memblock', 'reserved.cnt')
        region = ramdump.read_structure_field('memblock', 'struct memblock', 'reserved.regions')
        for i in range(cnt):
            start = ramdump.read_structure_field(region, 'struct memblock_region', 'base')
            size = ramdump.read_structure_field(region, 'struct memblock_region', 'size')
            memory_area_instance = memory_area("reserved", start, size)
            if any(x.base == memory_area_instance.base for x in list_memory_area) == False:
                list_memory_area.append(memory_area_instance)


    def get_iomem_resource(self, ramdump, list_memory_area):
        iomem_resource_addr = ramdump.address_of('iomem_resource')
        iomem_resource_start = iomem_resource_addr

        start = ramdump.read_structure_field(iomem_resource_start, 'struct resource', 'start')
        end = ramdump.read_structure_field(iomem_resource_start, 'struct resource', 'end')
        offset_name = ramdump.field_offset('struct resource', 'name')
        sibling = ramdump.read_structure_field(iomem_resource_start, 'struct resource', 'sibling')
        child = ramdump.read_structure_field(iomem_resource_start, 'struct resource', 'child')
        name_address = ramdump.read_pointer(iomem_resource_start + offset_name)
        name = cleanupString(ramdump.read_cstring(name_address, 16))
        iomem_resource_start = child

        while iomem_resource_start != 0:
            start = ramdump.read_structure_field(iomem_resource_start, 'struct resource', 'start')
            end = ramdump.read_structure_field(iomem_resource_start, 'struct resource', 'end')
            offset_name = ramdump.field_offset('struct resource', 'name')
            sibling = ramdump.read_structure_field(iomem_resource_start, 'struct resource', 'sibling')
            child = ramdump.read_structure_field(iomem_resource_start, 'struct resource', 'child')
            name_address = ramdump.read_pointer(iomem_resource_start + offset_name)
            name = cleanupString(ramdump.read_cstring(name_address))
            memory_area_instance = memory_area(name, start, end - start)
            list_memory_area.append(memory_area_instance)
            if sibling == 0:
                break
            iomem_resource_start = sibling


    def parse(self):
        list_memory_area = []
        self.get_reserved_mem(self.ramdump, list_memory_area)
        self.get_cma_areas(self.ramdump, list_memory_area)
        self.get_kernel_resource(list_memory_area)
        self.get_memory_block(self.ramdump, list_memory_area)
        self.get_iomem_resource(self.ramdump, list_memory_area)
        fmap = open(self.ramdump.outdir + "/reserved_mem.txt", "w")
        print("name											                  base 				end 				size 						  size in KB\n", file = fmap)
        new_list = sorted(list_memory_area, key=lambda c: c.base, reverse=False)
        for i in range(len(new_list)):
            memory_area_instance = new_list[i]
            print("----------------------------------------------------------------------------------------------------------------------------------------------",
                file=fmap)
            print("%-64s 0x%-16x 0x%-16x 0x%-16x  %16d" % (memory_area_instance.name,
                                                           memory_area_instance.base,
                                                           memory_area_instance.base + memory_area_instance.size,
                                                           memory_area_instance.size, memory_area_instance.size / 1024),
                  file=fmap)
        fmap.close()

@register_parser('--print-softirq-stat', 'Print softirq pending info ')
class SoftirqStat(RamParser):

    def parse(self):
        parse_softirq_stat(self.ramdump)


@register_parser('--print-qsee-log', 'Extract qsee com logs')
class ParseQseeLog(RamParser):
    def parse(self):
        do_parse_qsee_log(self.ramdump)
        anomaly = Anomaly()
        anomaly.setOutputDir(self.ramdump.outdir)
        return_string = check_qseecom_invalid_cmds(self.ramdump)
        if len(return_string):
            anomaly.addWarning("HLOS", "qsee_log.txt", "{0}".format(return_string))
