# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 and
# only version 2 as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.

import linux_list
import linux_radix_tree
import os
import shutil
import traceback

from importlib import import_module
from math import log2
from parser_util import RamParser
from parsers.gpu.gmu_info import generate_gmu_t32_files
from parsers.gpu.gpu_snapshot import extract_gmu_mem_from_snapshot
from parsers.gpu.gpuinfo_common import *
from print_out import print_out_str


class GpuMinidumpParser(RamParser):
    def __init__(self, dump):
        super(GpuMinidumpParser, self).__init__(dump)

        self.parser_list = [
            (self.parse_kgsl_driver, "KGSL", 'gpuinfo.txt'),
            (self.parse_pwrctrl_data, "KGSL Power", 'gpuinfo.txt'),
            (self.parse_kgsl_mem, "KGSL Memory Stats", 'gpuinfo.txt'),
            (self.parse_rb_inflight_data, "Ringbuffer and Inflight Queues",
             'gpuinfo.txt'),
            (self.parse_globals, "Globals", 'gpuinfo.txt'),
            (self.parse_preempt_data, "Preemption", 'gpuinfo.txt'),
            (self.parse_dispatcher_data, "Dispatcher", 'gpuinfo.txt'),
            (self.parse_scratch_memory, "Scratch Memory", 'gpuinfo.txt'),
            (self.parse_vrb_info, "VRB", 'gpuinfo.txt'),
            (self.parse_hwsched_info, "HWSCHED", 'gpuinfo.txt'),
            (self.parse_dcvs_tunables, "GMU DCVS Tunables", 'gpuinfo.txt'),
            (self.parse_memstore_memory, "Memstore", 'gpuinfo.txt'),
            (self.parse_context_data, "Open Contexts", 'gpuinfo.txt'),
            (self.parse_active_context_data, "Active Contexts", 'gpuinfo.txt'),
            (self.parse_open_process_data, "Open Processes", 'gpuinfo.txt'),
            (self.parse_pagetables, "Process Pagetables", 'gpuinfo.txt'),
            (self.parse_gmu_data, "GMU Details", 'gpuinfo.txt'),
            (self.dump_gpu_snapshot, "GPU Snapshot", 'gpuinfo.txt'),
            (self.dump_atomic_snapshot, "Atomic GPU Snapshot", 'gpuinfo.txt'),
            (self.parse_fence_data, "Fences", 'gpu_sync_fences.txt'),
            (self.parse_gpu_dcvs_data, "GPU DCVS Info", 'gpuinfo.txt'),
            (self.parse_non_context_data, "Non Context Overrides", 'gpuinfo.txt'),
        ]

    def parse(self):
        kgsl_driver_addr = self.ramdump.get_section_address(
            "kgsl_driver")[0][0]
        kgsl_driver = self.ramdump.read_datatype(kgsl_driver_addr,
                                                 "struct kgsl_driver")
        self.devp = getattr(kgsl_driver, 'devp')[0]
        file_path = os.path.join(self.ramdump.autodump, "md_KVA_DUMP.BIN")

        if not os.path.exists(file_path):
            print_out_str("GPU info: KVA_DUMP.BIN file not found at " + file_path)
            return

        mod = import_module('elftools.elf.elffile')
        ELFFile = mod.ELFFile
        fd = None
        try:
            fd = open(file_path, 'rb')
            self.kva_elf = ELFFile(fd)
            for subparser in self.parser_list:
                try:
                    self.out = self.ramdump.open_file('gpu_parser/' + \
                                                      subparser[2], 'a')
                    self.write(subparser[1].center(90, '-') + '\n')
                    subparser[0](self.ramdump)
                    self.writeln()
                    self.out.close()
                except Exception as e:
                    print_out_str(f"GPU info: Parsing failed in {subparser[0].__name__}: {str(e)}")
                    print_out_str(traceback.format_exc())
        finally:
            if fd:
                fd.close()

    def writeln(self, string=""):
        self.out.write(string + '\n')

    def write(self, string):
        self.out.write(string)

    def atomic_read(self, struct_addr, structure, name, dump):
        addr = struct_addr + dump.field_offset(structure, name)
        value = dump.read_s32(addr)
        return value

    def parse_kgsl_driver(self, dump):
        kgsl_device = self.ramdump.read_datatype(self.devp,
                                                 "struct kgsl_device")
        adreno_device = self.ramdump.read_datatype(self.devp,
                                                   "struct adreno_device")
        self.ramdump.print_struct(kgsl_device,
                                  self.out, ['open_count', 'state',
                                             'requested_state', 'speed_bin',
                                             'reset_counter',
                                             'host_based_dcvs', 'l3_vote', ])
        adreno_field_list = adreno_boolean_data + ['ft_policy',
                                                    'dcvs_tuning_mingap_lvl',
                                                    'dcvs_tuning_numbusy_lvl',
                                                    'ifpc_count', ]
        self.ramdump.print_struct(adreno_device, self.out, adreno_field_list)
        active_cnt = self.atomic_read(self.devp, 'struct kgsl_device',
                                      'active_cnt', dump)
        self.writeln('active_cnt: ' + str(active_cnt))

    def parse_kgsl_mem(self, dump):
        kgsl_driver_addr = self.ramdump.get_section_address(
            "kgsl_driver")[0][0]
        stats_offset = dump.field_offset('struct kgsl_driver',
                                         'stats')
        stats_addr = kgsl_driver_addr + stats_offset
        page_alloc_addr = stats_addr + 16
        page_alloc = dump.read_s64(page_alloc_addr)
        coherent_addr = stats_addr + 32
        coherent = dump.read_s64(coherent_addr)
        secure_addr = stats_addr + 48
        secure = dump.read_s64(secure_addr)
        self.writeln('KGSL Total: ' + str_convert_to_kb(secure +
                     page_alloc + coherent))
        self.writeln('\tsecure: ' + str_convert_to_kb(secure))
        self.writeln('\tnon-secure: ' + str_convert_to_kb(page_alloc +
                     coherent))
        self.writeln('\t\tpage_alloc: ' + str_convert_to_kb(page_alloc))
        self.writeln('\t\tcoherent: ' + str_convert_to_kb(coherent))

    def parse_pwrctrl_data(self, dump):
        pwrctrl_offset = dump.field_offset('struct kgsl_device',
                                           'pwrctrl')
        pwrctrl_addr = self.devp + pwrctrl_offset
        pwrctrl = self.ramdump.read_datatype(pwrctrl_addr,
                                             'struct kgsl_pwrctrl')
        self.writeln('pwrctrl_address:  ' + strhex(pwrctrl_addr))
        pwrctrl_list = pwrctrl_data + ['bus_control']
        self.ramdump.print_struct(pwrctrl, self.out, pwrctrl_list)
        interval_timeout = self.atomic_read(pwrctrl_addr,
                                            'struct kgsl_pwrctrl',
                                            'interval_timeout', dump)
        num_pwrlevels = getattr(pwrctrl, 'num_pwrlevels')
        power_flags = getattr(pwrctrl, 'power_flags')
        ctrl_flags = getattr(pwrctrl, 'ctrl_flags')
        self.writeln('Interval_timeout: ' + str(interval_timeout))
        self.writeln('power_flags: ' + strhex(power_flags))
        self.writeln('ctrl_flags: ' + strhex(ctrl_flags))

        pwr_levels_result = []
        pwrlevels_base_address = pwrctrl_addr + \
            dump.field_offset('struct kgsl_pwrctrl', 'pwrlevels')

        for i in range(0, num_pwrlevels):
            pwr_levels_temp = []
            pwrlevels_array_idx_addr = dump.array_index(
                pwrlevels_base_address, "struct kgsl_pwrlevel", i)
            pwrlevels = self.ramdump.read_datatype(pwrlevels_array_idx_addr,
                                                   'struct kgsl_pwrlevel')
            gpu_freq = getattr(pwrlevels, 'gpu_freq')
            bus_freq = getattr(pwrlevels, 'bus_freq')
            bus_min = getattr(pwrlevels, 'bus_min')
            bus_max = getattr(pwrlevels, 'bus_max')
            acd_level = getattr(pwrlevels, 'acd_level')
            if acd_level is None:
                acd_level = 0
            pwr_levels_temp.append(pwrlevels_array_idx_addr)
            pwr_levels_temp.append(gpu_freq)
            pwr_levels_temp.append(bus_freq)
            pwr_levels_temp.append(bus_min)
            pwr_levels_temp.append(bus_max)
            pwr_levels_temp.append(acd_level)
            pwr_levels_result.append(pwr_levels_temp)

        self.writeln('pwrlevels_base_address:  ' +
                     strhex(pwrlevels_base_address))

        format_str = '{0:<20} {1:<20} {2:<20} {3:<20} {4:<20} {5:<20}'
        self.writeln(format_str.format("INDEX", "GPU_FREQ", "BUS_FREQ",
                                       "BUS_MIN", "BUS_MAX", "ACD_LEVEL"))

        index = 0
        for powerlevel in pwr_levels_result:
            print_str = format_str.format(index, powerlevel[1], powerlevel[2],
                                          powerlevel[3], powerlevel[4],
                                          strhex(powerlevel[5]))
            self.writeln(print_str)
            index = index + 1

    def parse_globals(self, dump):
        format_str = '{0:33} {1:30} {2:20} '
        self.writeln(format_str.format("NAME", "HOSTPTR", "MEMDESC_SIZE"))
        for s in self.kva_elf.iter_sections():
            start = int(s.header['sh_addr'])
            size = int(s.header['sh_size'])
            if start == 0x0:
                continue

            if s.name.startswith("kgsl_global_"):
                self.writeln(format_str.format(s.name, strhex(start), str(size)))
                filename = 'gpu_parser/globals/{0}_{1}.bin'.format(s.name, strhex(start))
                file = dump.open_file(filename, 'wb')
                data = dump.get_bin_data(start, size)
                file.write(data)
                file.close()

    def parse_preempt_data(self, dump):
        preempt_offset = dump.field_offset('struct adreno_device',
                                           'preempt')
        preempt_addr = self.devp + preempt_offset
        preempt = self.ramdump.read_datatype(preempt_addr,
                                             "struct adreno_preemption")
        state = self.atomic_read(preempt_addr, 'struct adreno_preemption',
                                 'state', dump)
        count = getattr(preempt, 'count')
        preempt_level = getattr(preempt, 'preempt_level')

        self.writeln('state: ' + str(state))
        self.writeln('count: ' + str(count))
        self.writeln('preempt_level: ' + str(preempt_level))

    def parse_dispatcher_data(self, dump):
        dispatcher_offset = dump.field_offset('struct adreno_device',
                                              'preempt')
        dispatcher_addr = self.devp + dispatcher_offset
        dispatcher = self.ramdump.read_datatype(dispatcher_addr,
                                                "struct adreno_dispatcher")
        inflight = getattr(dispatcher, 'inflight')
        self.writeln('inflight: ' + str(inflight))

    def parse_dispatcher_queues(self, arr_base, shift, queue_name):
        self.write(queue_name + ': ')
        active_jobs = False
        for i in range(16):
            arr = self.ramdump.read_datatype(arr_base,
                                             "struct llist_head")
            first = getattr(arr, 'first')
            if first != 0:
                if not active_jobs:
                    self.writeln('')
                self.writeln('\t' + queue_name + '[' + str(i) +
                             '].first: ' + strhex(first))
                active_jobs = True
            arr_base += shift

        if not active_jobs:
            self.writeln('0x0')

    def parse_vrb_info(self, dump):
        hostptr, size = self.get_address_of('kgsl_gmu_vrb')
        self.writeln("hostptr: " + strhex(hostptr))
        self.writeln("size: " + strhex(size))
        def add_increment(x, y): return x + 4*y

        addr = add_increment(hostptr, VRB_PREEMPT_COUNT_TOTAL_L0_IDX)
        preempt_count_total_l0 = dump.read_u32(addr)
        addr = add_increment(hostptr, VRB_PREEMPT_COUNT_TOTAL_L1A_IDX)
        preempt_count_total_l1A = dump.read_u32(addr)
        addr = add_increment(hostptr, VRB_PREEMPT_COUNT_TOTAL_L1B_IDX)
        preempt_count_total_l1B = dump.read_u32(addr)

        format_str = '{0:20} {1:20}'
        self.writeln(format_str.format("Preempt_level", "Value"))
        self.writeln(format_str.format('L0', str(preempt_count_total_l0)))
        self.writeln(format_str.format('L1A', str(preempt_count_total_l1A)))
        self.writeln(format_str.format('L1B', str(preempt_count_total_l1B)))

    def parse_hwsched_info(self, dump):
        hwsched_offset = dump.field_offset('struct adreno_device',
                                           'hwsched')
        hwsched_addr = self.devp + hwsched_offset
        hwsched = self.ramdump.read_datatype(hwsched_addr,
                                             "struct adreno_hwsched")
        flags = getattr(hwsched, 'flags')
        self.writeln('flags: ' + strhex(flags))
        for i, flag in enumerate(hwsched_flags_data):
            value = (flags >> i) & 1
            self.writeln(f'{flag}: ' + str(value))

    def parse_dcvs_tunables(self, dump):
        def get_tunable_value(base_addr, struct_name, field_name):
            offset = dump.field_offset('struct adreno_hwsched', field_name)
            addr = base_addr + offset
            dcvs_struct = self.ramdump.read_datatype(addr, struct_name)
            return getattr(dcvs_struct, 'value')

        hwsched_offset = dump.field_offset('struct adreno_device', 'hwsched')
        hwsched_addr = self.devp + hwsched_offset

        self.writeln(f'{"Tunable Name":<35}{"Default Val":<15}{"Sysfs Val"}')

        for index, tunable in enumerate(DCVS_Tunables_list):
            default_field = f'default_dcvs_tunables[{index}]'
            sysfs_field = f'sysfs_dcvs_tunables[{index}]'

            default_val = get_tunable_value(hwsched_addr, "struct adreno_dcvs_tunable",
                default_field)
            sysfs_val = get_tunable_value(hwsched_addr, "struct adreno_dcvs_tunable",
                sysfs_field)

            self.writeln(f'{tunable:<35}{strhex(default_val):<15}{strhex(sysfs_val)}')

    def parse_gpu_dcvs_data(self, dump):
        kgsl_device = self.ramdump.read_datatype(self.devp,
                                                 "struct kgsl_device")
        state = getattr(kgsl_device, 'state')
        # Skip dumping and extraction of the DCVS data if GPU is not
        # in active state.
        if state == 2:
            adreno_tz_data_addr, size = self.get_address_of(
                'kgsl_adreno_tz_data')
            bin_offset = dump.field_offset(
                'struct devfreq_msm_adreno_tz_data', 'bin')
            bin_addr = adreno_tz_data_addr + bin_offset
            total_time = dump.read_s64(bin_addr)
            busy_time = dump.read_s64(bin_addr + 8)

            bus_offset = dump.field_offset(
                'struct devfreq_msm_adreno_tz_data', 'bus')
            bus_addr = adreno_tz_data_addr + bus_offset
            ram_time = dump.read_u64(bus_addr + 8)
            ram_wait = dump.read_u64(bus_addr + 16)

            adreno_tz_data = self.ramdump.read_datatype(
                adreno_tz_data_addr, 'struct devfreq_msm_adreno_tz_data')
            mod_percent = getattr(adreno_tz_data, 'mod_percent')

            self.writeln("total_time: " + str(total_time))
            self.writeln("busy_time: " + str(busy_time))
            self.writeln("ram_time: " + str(ram_time))
            self.writeln("ram_wait: " + str(ram_wait))
            self.writeln("mod_percent: " + str(mod_percent))
        else:
            self.writeln("DCVS data dump skipped if GPU state is not ACTIVE")

    def parse_pagetables(self, dump):
        format_str = '{0:14}'
        self.writeln(format_str.format("PID"))
        kgsl_driver_addr = self.ramdump.get_section_address(
            "kgsl_driver")[0][0]
        node_addr = kgsl_driver_addr + dump.field_offset('struct kgsl_driver',
                                                         'pagetable_list')
        list_elem_offset = dump.field_offset(
                            'struct kgsl_pagetable', 'list')
        pagetable_list_walker = linux_list.ListWalker(
                                    dump, node_addr, list_elem_offset)
        pagetable_list_walker.walk(self.walk_pagetable,
                                   dump, format_str)

    def walk_pagetable(self, pt_base_addr, dump, format_str):
        pagetable = self.ramdump.read_datatype(pt_base_addr,
                                               "struct kgsl_pagetable")
        pid = getattr(pagetable, 'name')
        if pid == 0 or pid == 1:
            return

        self.writeln(format_str.format(
            str(pid)))

    def parse_rb_inflight_data(self, dump):
        rb_base_addr = self.devp + dump.field_offset('struct adreno_device',
                                                     'ringbuffers')
        ringbuffers = []
        inflight_queue_result = []

        for i in range(0, KGSL_PRIORITY_MAX_RB_LEVELS):
            ringbuffers_temp = []
            rb_array_index_addr = dump.array_index(
                rb_base_addr, "struct adreno_ringbuffer", i)
            rb_array_index = self.ramdump.read_datatype(
                rb_array_index_addr, "struct adreno_ringbuffer")
            wptr = getattr(rb_array_index, 'wptr')
            _wptr = getattr(rb_array_index, '_wptr')
            last_wptr = getattr(rb_array_index, 'last_wptr')
            id = getattr(rb_array_index, 'id')
            flags = getattr(rb_array_index, 'flags')

            drawctxt_active_addr = getattr(rb_array_index, 'drawctxt_active')

            if drawctxt_active_addr != 0:
                drawctxt_active = self.ramdump.read_datatype(
                    drawctxt_active_addr, "struct kgsl_context")
                kgsl_context_id = getattr(drawctxt_active, 'id')
                proc_priv_val = getattr(drawctxt_active, 'proc_priv')
                if proc_priv_val != 0:
                    comm_offset = dump.field_offset(
                        'struct kgsl_process_private', 'comm')
                    process_name = dump.read_cstring(proc_priv_val
                                                     + comm_offset)
                else:
                    process_name = "NULL"
            else:
                kgsl_context_id = "NULL"
                process_name = "NULL"

            dispatch_q_address = rb_array_index_addr + \
                dump.field_offset('struct adreno_ringbuffer', 'dispatch_q')
            dispatch_q = self.ramdump.read_datatype(
                dispatch_q_address, 'struct adreno_dispatcher_drawqueue')
            inflight = getattr(dispatch_q, 'inflight')
            cmd_q_address = dispatch_q_address + dump.field_offset(
                'struct adreno_dispatcher_drawqueue', 'cmd_q')
            head = getattr(dispatch_q, 'head')
            tail = getattr(dispatch_q, 'tail')

            dispatcher_result = []
            while head is not tail:
                dispatcher_temp = []
                inflight_queue_index_address = dump.array_index(
                    cmd_q_address, 'struct kgsl_drawobj_cmd *', head)
                inflight_queue_index_value = dump.read_word(
                    inflight_queue_index_address)

                if inflight_queue_index_value != 0:
                    inflight_queue_index = self.ramdump.read_datatype(
                        inflight_queue_index_value, 'struct kgsl_drawobj_cmd')
                    global_ts = getattr(inflight_queue_index, 'global_ts')
                    fault_policy = getattr(inflight_queue_index,
                                           'fault_policy')
                    fault_recovery = getattr(inflight_queue_index,
                                             'fault_recovery')

                    base_address = inflight_queue_index_value + \
                        dump.field_offset('struct kgsl_drawobj_cmd', 'base')
                    base = self.ramdump.read_datatype(base_address,
                                                      'struct kgsl_drawobj')
                    drawobj_type = getattr(base, 'type')
                    timestamp = getattr(base, 'timestamp')
                    flags = getattr(base, 'flags')
                    context_pointer = dump.read_pointer(dump.field_offset(
                        'struct kgsl_drawobj', 'context')+base_address)
                    context = self.ramdump.read_datatype(
                        context_pointer, 'struct kgsl_context')
                    context_id = getattr(context, 'id')
                    proc_priv = getattr(context, 'proc_priv')
                    proc_priv = self.ramdump.read_datatype(
                        proc_priv, 'struct kgsl_process_private')
                    pid = getattr(proc_priv, 'pid')
                    upid_offset = dump.field_offset('struct pid', 'numbers')
                    upid = dump.read_int(pid + upid_offset)
                else:
                    global_ts = 'NULL'
                    fault_policy = 'NULL'
                    fault_recovery = 'NULL'
                    drawobj_type = 'NULL'
                    timestamp = 'NULL'
                    flags = 'NULL'
                    context_id = 'NULL'
                    pid = 'NULL'

                dispatcher_temp.extend([i, global_ts, fault_policy,
                                        fault_recovery, drawobj_type,
                                        timestamp, flags, context_id, upid])

                dispatcher_result.append(dispatcher_temp)
                head = (head + 1) % ADRENO_DISPATCH_DRAWQUEUE_SIZE

            inflight_queue_result.append(dispatcher_result)

            ringbuffers_temp.append(rb_array_index_addr)
            ringbuffers_temp.append(wptr)
            ringbuffers_temp.append(_wptr)
            ringbuffers_temp.append(last_wptr)
            ringbuffers_temp.append(id)
            ringbuffers_temp.append(flags)
            ringbuffers_temp.append(kgsl_context_id)
            ringbuffers_temp.append(process_name)
            ringbuffers_temp.append(inflight)
            ringbuffers.append(ringbuffers_temp)

        format_str = "{0:20} {1:20} {2:20} {3:20} " \
            "{4:20} {5:20} {6:20} {7:20} {8:20}"

        print_str = format_str.format('INDEX', 'WPTR', '_WPTR', 'LAST_WPTR',
                                      'ID', 'FLAGS', 'KGSL_CONTEXT_ID',
                                      'PROCESS_NAME', 'INFLIGHT')
        self.writeln(print_str)

        index = 0
        for rb in ringbuffers:
            print_str = format_str.format(str(index), str(rb[1]), str(rb[2]),
                                          str(rb[3]), str(rb[4]), str(rb[5]),
                                          str(rb[6]), str(rb[7]), str(rb[8]))
            self.writeln(print_str)
            index = index + 1

        self.writeln()
        self.writeln("Inflight Queues:")

        format_str = "{0:20} {1:20} {2:20} {3:20} {4:20} " \
            "{5:20} {6:20} {7:20} {8:20}"

        print_str = format_str.format("ringbuffer", "global_ts",
                                      "fault_policy", "fault_recovery",
                                      "type", "timestamp", "flags",
                                      "context_id", "pid")
        self.writeln(print_str)

        # Flatten the 3D list to 1D list
        queues = sum(inflight_queue_result, [])
        for queue in queues:
            # Skip if all the entries excluding rb of the queue are empty
            if all([i == 'NULL' for i in queue[1:]]):
                pass

            self.writeln(format_str.format(str(queue[0]), str(queue[1]),
                                           str(queue[2]), str(queue[3]),
                                           str(queue[4]), str(queue[5]),
                                           str(queue[6]), str(queue[7]),
                                           str(queue[8])))

    def print_context_data(self, ctx_addr, format_str):
        dump = self.ramdump
        kgsl_context = self.ramdump.read_datatype(ctx_addr,
                                                  "struct kgsl_context")
        context_id = str(getattr(kgsl_context, 'id'))
        if context_id == "0":
            return
        proc_priv_offset = dump.field_offset('struct kgsl_context',
                                             'proc_priv')
        proc_priv = dump.read_pointer(ctx_addr + proc_priv_offset)
        comm_offset = dump.field_offset('struct kgsl_process_private', 'comm')
        comm = str(dump.read_cstring(proc_priv + comm_offset))
        adreno_context = self.ramdump.read_datatype(ctx_addr,
                                                    "struct adreno_context")
        ctx_type = getattr(adreno_context, 'type')
        flags = getattr(kgsl_context, 'flags')
        priv = getattr(kgsl_context, 'priv')
        is_secure = bool(flags & KGSL_CONTEXT_SECURE)
        priv_str = ['-'] * 11
        for i, (bit, char, prop) in enumerate(kgsl_ctx_priv):
            if bool(bit & priv):
                priv_str[i] = char
        priv_str = ''.join(priv_str)

        ktimeline_offset = dump.field_offset('struct kgsl_context',
                                             'ktimeline')
        ktimeline_addr = dump.read_pointer(ctx_addr + ktimeline_offset)
        ktimeline = self.ramdump.read_datatype(ktimeline_addr,
                                               "struct kgsl_sync_timeline")
        ktimeline_last_ts = getattr(ktimeline, 'last_timestamp')
        self.writeln(format_str.format(context_id, comm,
                     strhex(ctx_addr), kgsl_ctx_type[ctx_type], strhex(flags),
                     str(is_secure), priv_str, str(ktimeline_last_ts)))

    def parse_context_data(self, dump):
        format_str = '{0:10} {1:20} {2:28} {3:12} ' + \
                     '{4:12} {5:12} {6:14} {7:16} '
        self.writeln(format_str.format("CTX_ID", "PROCESS_NAME",
                                       "ADRENO_DRAWCTX_PTR", "CTX_TYPE",
                                       "FLAGS", "IS_SECURE", "PRIV",
                                       "TIMELINE_LST_TS"))
        for s in self.kva_elf.iter_sections():
            start = int(s.header['sh_addr'])
            if start == 0x0:
                continue

            if s.name.startswith("kgsl_adreno_ctx"):
                dump = self.ramdump
                kgsl_context = self.ramdump.read_datatype(
                    start, "struct kgsl_context")
                context_id = str(getattr(kgsl_context, 'id'))
                if context_id == "0":
                    continue
                proc_priv_offset = dump.field_offset('struct kgsl_context',
                                                     'proc_priv')
                proc_priv = dump.read_pointer(start + proc_priv_offset)
                comm_offset = dump.field_offset('struct kgsl_process_private',
                                                'comm')
                comm = str(dump.read_cstring(proc_priv + comm_offset))
                adreno_context = self.ramdump.read_datatype(
                    start, "struct adreno_context")
                ctx_type = getattr(adreno_context, 'type')
                flags = getattr(kgsl_context, 'flags')
                priv = getattr(kgsl_context, 'priv')
                is_secure = bool(flags & KGSL_CONTEXT_SECURE)
                priv_str = ['-'] * 11
                for i, (bit, char, prop) in enumerate(kgsl_ctx_priv):
                    if bool(bit & priv):
                        priv_str[i] = char
                priv_str = ''.join(priv_str)

                ktimeline_offset = dump.field_offset('struct kgsl_context',
                                                     'ktimeline')
                ktimeline_addr = dump.read_pointer(start + ktimeline_offset)
                ktimeline = self.ramdump.read_datatype(
                    ktimeline_addr, "struct kgsl_sync_timeline")
                ktimeline_last_ts = getattr(ktimeline, 'last_timestamp')
                self.writeln(format_str.format(context_id, comm,
                             strhex(start), kgsl_ctx_type[ctx_type],
                             strhex(flags), str(is_secure), priv_str,
                             str(ktimeline_last_ts)))

        self.writeln('\nPriv key:')
        for (bit, char, prop) in kgsl_ctx_priv:
            self.write('\'' + char + '\'' + ': ' + prop + ', ')
        self.writeln()

    def parse_gmu_data(self, dump):
        hostptr, size = self.get_address_of('kgsl_gmu_log')

        self.writeln('Trace Details:')
        self.writeln('\tStart Address: ' + strhex(hostptr))
        self.writeln('\tSize: ' + str_convert_to_kb(size))

        if size == 0:
            self.writeln('Invalid size. Aborting gmu trace dump.')
            return
        else:
            file = self.ramdump.open_file('gpu_parser/gmu_trace.bin', 'wb')
            self.writeln('Dumping ' + str_convert_to_kb(size) +
                         ' starting from ' + strhex(hostptr) +
                         ' to gmu_trace.bin')
            data = self.ramdump.get_bin_data(hostptr, size)
            file.write(data)
            file.close()

        gmu_core = self.devp + dump.field_offset('struct kgsl_device',
                                                 'gmu_core')
        gmu_core_struct = self.ramdump.read_datatype(gmu_core,
                                                     "struct gmu_core_device")
        gmu_on = getattr(gmu_core_struct, 'flags')
        if not ((gmu_on >> 4) & 1):
            self.writeln('GMU not enabled.')
            return
        gen8_hwsched_device_addr, size2 = self.get_address_of(
            'kgsl_hwsched_device')
        gen8_device_addr = gen8_hwsched_device_addr + \
            dump.field_offset('struct gen8_hwsched_device', 'gen8_dev')
        gen8_gmu_device_addr = gen8_device_addr + dump.field_offset(
                                                  'struct gen8_device', 'gmu')
        gen8_gmu_device = self.ramdump.read_datatype(gen8_gmu_device_addr,
                                                     "struct gen8_gmu_device")

        idle_level = getattr(gen8_gmu_device, 'idle_level')
        log_stream_enable = getattr(gen8_gmu_device, 'log_stream_enable')
        warmboot_enable = getattr(gmu_core_struct, 'warmboot_enabled')
        global_entries = getattr(gmu_core_struct, 'global_entries')
        cm3_fault = self.atomic_read(gen8_gmu_device_addr,
                                     'struct gen8_gmu_device', 'cm3_fault',
                                     dump)
        self.writeln('idle_level: ' + str(idle_level))
        self.writeln('log_stream_enable: ' + str(log_stream_enable))
        self.writeln('cm3_fault: ' + str(cm3_fault))
        self.writeln('warmboot_enable: ' + str(warmboot_enable))
        self.writeln('global_entries: ' + str(global_entries))

    def parse_active_context_data(self, dump):
        format_str = '{0:10} {1:20} {2:28} {3:12} ' + \
                     '{4:12} {5:12} {6:14} {7:16}'
        self.writeln(format_str.format("CTX_ID", "PROCESS_NAME",
                                       "ADRENO_DRAWCTX_PTR", "CTX_TYPE",
                                       "FLAGS", "IS_SECURE", "PRIV",
                                       "TIMELINE_LST_TS"))
        node_addr = self.devp + dump.field_offset(
                                         'struct adreno_device',
                                         'active_list')
        list_elem_offset = dump.field_offset('struct adreno_context',
                                             'active_node')
        active_context_list_walker = linux_list.ListWalker(dump, node_addr,
                                                           list_elem_offset)
        active_context_list_walker.walk(self.print_context_data, format_str)
        self.writeln('\nPriv key:')
        for (bit, char, prop) in kgsl_ctx_priv:
            self.write('\'' + char + '\'' + ': ' + prop + ', ')
        self.writeln()

    def parse_fence_data(self, dump):
        for s in self.kva_elf.iter_sections():
            start = int(s.header['sh_addr'])
            if start == 0x0:
                continue

            if s.name.startswith("kgsl_sync_timeline_ctxt"):
                self.write('{:50}0x{:x}\n'.format(s.name, start))
                kgsl_sync_timeline = self.ramdump.read_datatype(
                    start, "struct kgsl_sync_timeline")
                kgsl_sync_timeline_name = getattr(kgsl_sync_timeline, 'name')
                kgsl_sync_timeline_last_ts = getattr(kgsl_sync_timeline,
                                                     'last_timestamp')
                kgsl_sync_timeline_kref_counter = dump.read_byte(start)
                self.writeln("\t" + "kgsl_sync_timeline_name: "
                             + str(kgsl_sync_timeline_name))
                self.writeln("\t" + "kgsl_sync_timeline_last_timestamp: "
                             + str(kgsl_sync_timeline_last_ts))
                self.writeln("\t" + "kgsl_sync_timeline_kref_counter: "
                             + str(kgsl_sync_timeline_kref_counter))

    def get_address_of(self, sname=""):
        file_path = os.path.join(self.ramdump.autodump, "md_KVA_DUMP.BIN")
        mod = import_module('elftools.elf.elffile')
        ELFFile = mod.ELFFile

        with open(file_path, 'rb') as fd:
            kva_elf = ELFFile(fd)
            for s in kva_elf.iter_sections():
                start = int(s.header['sh_addr'])
                size = int(s.header['sh_size'])
                if start == 0x0:
                    continue

                if s.name == sname:
                    return start, size
        return 0, 0

    def parse_non_context_data(self, dump):
        format_str = '{0:16} {1:16} {2:16} {3:16} {4:16}'
        self.writeln(format_str.format("offset", "pipelines", "value",
                                       "set", "list_type"))
        addr, size = self.get_address_of('kgsl_nc_overrides')
        struct_size = self.ramdump.sizeof('struct gen8_nonctxt_overrides')
        total_num = size/struct_size
        while(total_num):
            non_context = self.ramdump.read_datatype(
                addr, "struct gen8_nonctxt_overrides")
            offset = getattr(non_context, 'offset')
            pipelines = getattr(non_context, 'pipelines')
            value = getattr(non_context, 'val')
            set = getattr(non_context, 'set')
            list_type = getattr(non_context, 'list_type')
            self.writeln(format_str.format(strhex(offset), strhex(pipelines),
                         strhex(value), str(set), strhex(list_type)))
            addr = addr + struct_size
            total_num = total_num - 1

    def parse_memstore_memory(self, dump):
        hostptr, size = self.get_address_of('kgsl_global_memstore')
        parse_memstore_memory_common(dump, hostptr, size, self.writeln)

    def parse_scratch_memory(self, dump):
        hostptr, size = self.get_address_of('kgsl_global_scratch')

        self.write("hostptr:  " + strhex(hostptr) + "\n")

        def add_increment(x): return x + 4

        format_str = '{0:20} {1:20} {2:20}'
        self.writeln(format_str.format("Ringbuffer_id", "RPTR_Value",
                                       "CTXT_RESTORE_ADD"))

        rptr_0 = dump.read_s32(hostptr)
        hostptr = add_increment(hostptr)
        rptr_1 = dump.read_s32(hostptr)
        hostptr = add_increment(hostptr)
        rptr_2 = dump.read_s32(hostptr)
        hostptr = add_increment(hostptr)
        rptr_3 = dump.read_s32(hostptr)
        hostptr = add_increment(hostptr)
        ctxt_0 = dump.read_s32(hostptr)
        hostptr = add_increment(hostptr)
        ctxt_1 = dump.read_s32(hostptr)
        hostptr = add_increment(hostptr)
        ctxt_2 = dump.read_s32(hostptr)
        hostptr = add_increment(hostptr)
        ctxt_3 = dump.read_s32(hostptr)

        self.writeln(format_str.format(str(0), str(rptr_0), strhex(ctxt_0)))
        self.writeln(format_str.format(str(1), str(rptr_1), strhex(ctxt_1)))
        self.writeln(format_str.format(str(2), str(rptr_2), strhex(ctxt_2)))
        self.writeln(format_str.format(str(3), str(rptr_3), strhex(ctxt_3)))

    def dump_gpu_snapshot(self, dump):
        kgsl_device = self.ramdump.read_datatype(self.devp,
                                                 "struct kgsl_device")
        snapshot_faultcount = getattr(kgsl_device, 'snapshot_faultcount')
        self.writeln(str(snapshot_faultcount) + ' snapshot fault(s) detected.')

        force_panic = getattr(kgsl_device, 'force_panic')
        gmu_core_addr = self.devp + dump.field_offset('struct kgsl_device',
                                                      'gmu_core')
        gf_panic_addr = gmu_core_addr + \
            dump.field_offset("struct gmu_core_device", 'gf_panic')
        gf_panic = dump.read_s32(gf_panic_addr)
        self.writeln('force_panic: ' + str(force_panic))
        self.writeln('gf_panic: ' + str(gf_panic))

        if snapshot_faultcount == 0:
            self.writeln('No GPU hang, skipping snapshot dumping.')
            return

        source_path = os.path.join(self.ramdump.autodump, "md_GPU_SNAPSHOT.BIN")
        if not os.path.exists(source_path):
            self.writeln('GPU snapshot file not found: ' + source_path)
            return

        file_name = 'gpu_snapshot_memory.bpmd'
        file = self.ramdump.open_file('gpu_parser/' + file_name, 'wb')
        destination_path = os.path.join(self.ramdump.outdir, 'gpu_parser', file_name)
        shutil.copyfile(source_path, destination_path)

        snapshot_size = os.path.getsize(destination_path)
        self.writeln('Snapshot Details:')
        self.writeln('\tSize: ' + str_convert_to_kb(snapshot_size))

        file.close()

        extract_gmu_mem_from_snapshot(dump, "gpu_parser/" + file_name)
        generate_gmu_t32_files(dump)

    def dump_atomic_snapshot(self, dump):
        source_path = os.path.join(self.ramdump.autodump, "md_ATOMIC_GPU_S.BIN")

        if not os.path.exists(source_path):
            self.writeln('Atomic snapshot file not found: ' + source_path)
            return

        file_name = 'gpu_atomic_snapshot_memory.bpmd'
        file = self.ramdump.open_file('gpu_parser/' + file_name, 'wb')
        destination_path = os.path.join(self.ramdump.outdir, 'gpu_parser', file_name)
        shutil.copyfile(source_path, destination_path)

        snapshot_size = os.path.getsize(destination_path)
        self.writeln('Snapshot Details:')
        self.writeln('\tSize: ' + str_convert_to_kb(snapshot_size))

        file.close()

    def parse_open_process_data(self, dump):
        format_str = '{0:20} {1:20} {2:30} {3:20} {4:20} {5:10} ' \
                     '{6:20} {7:20}'
        self.writeln(format_str.format("PNAME", "PROCESS_PRIVATE_PTR",
                                       "KGSL_PAGETABLE_ADDRESS",
                                       "KGSL_CUR_MEMORY", "DMABUF_CUR_MEMORY",
                                       "CTX_CNT", "STATE", "CMDLINE STRING"))
        for s in self.kva_elf.iter_sections():
            start = int(s.header['sh_addr'])
            if start == 0x0:
                continue

            if s.name.startswith("kgsl_proc_priv"):
                kgsl_private = self.ramdump.read_datatype(
                    start, "struct kgsl_process_private")

                comm_offset = dump.field_offset('struct kgsl_process_private',
                                                'comm')
                pname = dump.read_cstring(start + comm_offset)

                kgsl_pagetable_address = getattr(kgsl_private, 'pagetable')

                stats_offset = dump.field_offset('struct kgsl_process_private',
                                                 'stats')
                stats_addr = start + stats_offset

                kgsl_mem = dump.read_slong(stats_addr)
                dmabuf_mem = dump.read_slong(stats_addr + (16 * 4))

                ctxt_count = self.atomic_read(start,
                                              'struct kgsl_process_private',
                                              'ctxt_count', dump)
                state = getattr(kgsl_private, 'state')
                cmdline_offset = getattr(kgsl_private, 'cmdline')
                cmdline_string = dump.read_cstring(dump.read_pointer(
                                           start +
                                           cmdline_offset))

                self.writeln(format_str.format(
                    str(pname), hex(start),
                    hex(kgsl_pagetable_address), str_convert_to_kb(kgsl_mem),
                    str_convert_to_kb(dmabuf_mem), str(ctxt_count),
                    hex(state), str(cmdline_string)))
