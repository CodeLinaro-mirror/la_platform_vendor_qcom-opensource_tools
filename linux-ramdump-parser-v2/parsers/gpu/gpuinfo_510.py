# Copyright (c) 2021 The Linux Foundation. All rights reserved.
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 and
# only version 2 as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

import linux_list
import linux_radix_tree
import struct
import traceback

from math import log2
from parser_util import RamParser
from parsers.gpu.gmu_info import generate_gmu_t32_files
from parsers.gpu.gpu_snapshot import create_snapshot_from_ramdump
from parsers.gpu.gpu_snapshot import extract_gmu_mem_from_snapshot
from parsers.gpu.gpu_eventlog import parse_eventlog_buffer
from parsers.gpu.gpuinfo_common import *
from print_out import print_out_str


class GpuParser_510(RamParser):
    def __init__(self, dump):
        super(GpuParser_510, self).__init__(dump)

        # List of all sub-parsers as (func, info, outfile) tuples.
        self.parser_list = [
            (self.parse_kgsl_data, "KGSL", 'gpuinfo.txt'),
            (self.parse_features_data, "Features", 'gpuinfo.txt'),
            (self.parse_pwrctrl_data, "KGSL Power", 'gpuinfo.txt'),
            (self.parse_kgsl_mem, "KGSL Memory Stats", 'gpuinfo.txt'),
            (self.parse_rb_inflight_data, "Ringbuffer and Inflight Queues",
             'gpuinfo.txt'),
            (self.parse_globals, "Globals", 'gpuinfo.txt'),
            (self.parse_preempt_data, "Preemption", 'gpuinfo.txt'),
            (self.parse_dispatcher_data, "Dispatcher", 'gpuinfo.txt'),
            (self.parse_mutex_data, "KGSL Mutexes", 'gpuinfo.txt'),
            (self.parse_scratch_memory, "Scratch Memory", 'gpuinfo.txt'),
            (self.parse_vrb_info, "VRB", 'gpuinfo.txt'),
            (self.parse_dcvs_tunables, "GMU DCVS Tunables", 'gpuinfo.txt'),
            (self.parse_active_fences, "Active Fences", 'hw_fences.txt'),
            (self.parse_hwsched_info, "HWSCHED", 'gpuinfo.txt'),
            (self.parse_memstore_memory, "Memstore", 'gpuinfo.txt'),
            (self.parse_context_data, "Open Contexts", 'gpuinfo.txt'),
            (self.parse_active_context_data, "Active Contexts", 'gpuinfo.txt'),
            (self.parse_open_process_data, "Open Processes", 'gpuinfo.txt'),
            (self.parse_pagetables, "Process Pagetables", 'gpuinfo.txt'),
            (self.parse_gmu_data, "GMU Details", 'gpuinfo.txt'),
            (self.dump_gpu_snapshot, "GPU Snapshot", 'gpuinfo.txt'),
            (self.dump_atomic_snapshot, "Atomic GPU Snapshot", 'gpuinfo.txt'),
            (self.parse_fence_data, "Fences", 'gpu_sync_fences.txt'),
            (self.parse_open_process_mementry, "Open Process Mementries",
             'open_process_mementries.txt'),
            (self.parse_eventlog_data, "Eventlog Buffer", 'eventlog.txt'),
            (self.parse_gpu_dcvs_data, "GPU DCVS Info",
             'gpuinfo.txt'),
            (self.parse_non_context_data, "Non Context Overrides", 'gpuinfo.txt'),
        ]

        self.rtw = linux_radix_tree.RadixTreeWalker(dump)

    def parse(self):
        self.devp = self.ramdump.read_pointer('kgsl_driver.devp')
        for subparser in self.parser_list:
            try:
                self.out = self.ramdump.open_file('gpu_parser/' + subparser[2],
                                                  'a')
                self.write(subparser[1].center(90, '-') + '\n')
                subparser[0](self.ramdump)
                self.writeln()
                self.out.close()
            except Exception:
                print_out_str("GPU info: Parsing failed in "
                              + subparser[0].__name__)
                print_out_str(traceback.format_exc())

    def write(self, string):
        self.out.write(string)

    def writeln(self, string=""):
        self.out.write(string + '\n')

    def print_context_data(self, ctx_addr, format_str):
        dump = self.ramdump
        context_id = str(dump.read_structure_field(
            ctx_addr, 'struct kgsl_context', 'id'))
        if context_id == "0":
            return

        proc_priv_offset = dump.field_offset('struct kgsl_context',
                                             'proc_priv')
        proc_priv = dump.read_pointer(ctx_addr + proc_priv_offset)
        pid = dump.read_structure_field(proc_priv,
                                        'struct kgsl_process_private', 'pid')
        upid_offset = dump.field_offset('struct pid', 'numbers')
        upid = dump.read_int(pid + upid_offset)

        comm_offset = dump.field_offset('struct kgsl_process_private', 'comm')
        comm = str(dump.read_cstring(proc_priv + comm_offset))
        if comm == '' or upid is None:
            return

        ctx_type = dump.read_structure_field(ctx_addr,
                                             'struct adreno_context', 'type')
        flags = dump.read_structure_field(ctx_addr,
                                          'struct kgsl_context', 'flags')
        priv = dump.read_structure_field(ctx_addr,
                                         'struct kgsl_context', 'priv')
        is_secure = bool(flags & KGSL_CONTEXT_SECURE)
        priv_str = ['-'] * 11
        for i, (bit, char, prop) in enumerate(kgsl_ctx_priv):
            if bool(bit & priv):
                priv_str[i] = char
        priv_str = ''.join(priv_str)

        ktimeline_offset = dump.field_offset('struct kgsl_context',
                                             'ktimeline')
        ktimeline_addr = dump.read_pointer(ctx_addr + ktimeline_offset)
        ktimeline_last_ts = dump.read_structure_field(
                ktimeline_addr, 'struct kgsl_sync_timeline', 'last_timestamp')

        memstore_obj = dump.read_structure_field(self.devp,
                                                 'struct kgsl_device',
                                                 'memstore')
        hostptr = dump.read_structure_field(memstore_obj,
                                            'struct kgsl_memdesc', 'hostptr')
        ctx_memstr_offset = int(context_id) * KGSL_DEVMEMSTORE_SIZE
        soptimestamp = dump.read_s32(hostptr + ctx_memstr_offset)
        eoptimestamp = dump.read_s32(hostptr + ctx_memstr_offset + 8)

        ctxt_queue = dump.struct_field_addr(ctx_addr, 'struct adreno_context',
                                            'gmu_context_queue')
        gmuaddr = dump.read_structure_field(ctxt_queue, 'struct kgsl_memdesc',
                                            'gmuaddr')

        self.writeln(format_str.format(context_id, str(upid), comm,
                     strhex(ctx_addr), kgsl_ctx_type[ctx_type], strhex(flags),
                     str(is_secure), priv_str, str(ktimeline_last_ts),
                     str(soptimestamp), str(eoptimestamp), str(gmuaddr)))

    def parse_context_data(self, dump):
        format_str = '{0:10} {1:10} {2:20} {3:28} {4:12} ' + \
                     '{5:12} {6:12} {7:14} {8:16} {9:14} {10:14} {11:30}'
        self.writeln(format_str.format("CTX_ID", "PID", "PROCESS_NAME",
                                       "ADRENO_DRAWCTX_PTR", "CTX_TYPE",
                                       "FLAGS", "IS_SECURE", "PRIV",
                                       "TIMELINE_LST_TS", "SOP_TS", "EOP_TS",
                                       "CTXQ_GMU_ADDR"))
        context_idr = dump.struct_field_addr(self.devp, 'struct kgsl_device',
                                             'context_idr')
        self.rtw.walk_radix_tree(context_idr,
                                 self.print_context_data, format_str)
        self.writeln('\nPriv key:')
        for (bit, char, prop) in kgsl_ctx_priv:
            self.write('\'' + char + '\'' + ': ' + prop + ', ')
        self.writeln()

    def parse_active_context_data(self, dump):
        format_str = '{0:10} {1:10} {2:20} {3:28} {4:12} ' + \
                     '{5:12} {6:12} {7:14} {8:16} {9:14} {10:14} {11:14}'
        self.writeln(format_str.format("CTX_ID", "PID", "PROCESS_NAME",
                                       "ADRENO_DRAWCTX_PTR", "CTX_TYPE",
                                       "FLAGS", "IS_SECURE", "PRIV",
                                       "TIMELINE_LST_TS", "SOP_TS", "EOP_TS",
                                       "CTXQ_GMU_ADDR"))
        node_addr = dump.struct_field_addr(self.devp, 'struct adreno_device',
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

    def parse_globals(self, dump):
        format_str = '{0:30} {1:30} {2:30} {3:20} {4:30} {5:12}'
        self.writeln(format_str.format("NAME", "MEMDESC_ADDR", "HOSTPTR",
                                       "MEMDESC_SIZE", "GPUADDR", "FLAGS"))
        node_addr = dump.struct_field_addr(self.devp, 'struct kgsl_device',
                                           'globals')
        list_elem_offset = dump.field_offset('struct kgsl_global_memdesc',
                                             'node')
        globals_list_walker = linux_list.ListWalker(dump, node_addr,
                                                    list_elem_offset)
        globals_list_walker.walk(self.__print_global_memdesc,
                                 format_str)

    def __print_global_memdesc(self, kgsl_global_memdesc_base, format_str):
        dump = self.ramdump
        name = dump.read_structure_field(kgsl_global_memdesc_base,
                                         'struct kgsl_global_memdesc', 'name')
        name = dump.read_cstring(name)
        gpuaddr = dump.read_structure_field(kgsl_global_memdesc_base,
                                            'struct kgsl_memdesc', 'gpuaddr')
        if name is None or gpuaddr == 0:
            return

        hostptr = dump.read_structure_field(kgsl_global_memdesc_base,
                                            'struct kgsl_memdesc', 'hostptr')
        size = dump.read_structure_field(kgsl_global_memdesc_base,
                                         'struct kgsl_memdesc', 'size')
        flags = self.prepare_global_memdesc_flags(kgsl_global_memdesc_base)

        self.writeln(format_str.format(name, hex(kgsl_global_memdesc_base),
                                       hex(hostptr), str(size), hex(gpuaddr),
                                       str(flags)))
        if (flags[2] != 's'):
            filename = 'gpu_parser/globals/{0}.bin'.format(
                name + '_' + hex(kgsl_global_memdesc_base))
            file = dump.open_file(filename, 'wb')
            data = dump.get_bin_data(hostptr, size)
            file.write(data)
            file.close()

    def prepare_global_memdesc_flags(self, memdesc_addr):
        '''
            Returns flag string with following legend:
            is_priveleged | is_readonly | is_secure | is_random | is_ucode
                  p/-     |    -/w      |    s/-    |    r/-    |   u/-
        '''
        dump = self.ramdump
        priv = dump.read_structure_field(memdesc_addr,
                                         'struct kgsl_memdesc', 'priv')
        mflags = dump.read_structure_field(memdesc_addr,
                                           'struct kgsl_memdesc', 'flags')
        flags = ['-'] * 5

        if bool(priv & KGSL_MEMDESC_PRIVILEGED):
            flags[0] = 'p'

        if not bool(mflags & KGSL_MEMFLAGS_GPUREADONLY):
            flags[1] = 'w'

        if bool(priv & KGSL_MEMDESC_SECURE):
            flags[2] = 's'

        if bool(priv & KGSL_MEMDESC_RANDOM):
            flags[3] = 'r'

        if bool(priv & KGSL_MEMDESC_UCODE):
            flags[4] = 'u'

        return ''.join(flags)

    def parse_open_process_mementry(self, dump):
        self.writeln('WARNING: Some nodes can be corrupted one, Ignore them.')
        format_str = '{0:20} {1:20} {2:12} {3:30} ' \
                     '{4:20} {5:20} {6:12} {7:20} {8:20} {9:12}'
        self.writeln(format_str.format("PID", "PNAME", "INDEX", "MEMDESC_ADDR",
                                       "MEMDESC_SIZE", "GPUADDR", "FLAGS",
                                       "USAGE", "PENDING_FREE", "PRIV"))

        node_addr = dump.address_of('kgsl_driver') + dump.field_offset(
            'struct kgsl_driver', 'process_list')
        list_elem_offset = dump.field_offset(
            'struct kgsl_process_private', 'list')
        open_process_list_walker = linux_list.ListWalker(
            dump, node_addr, list_elem_offset)
        open_process_list_walker.walk(
            self.__walk_process_mementry, dump, format_str)

    def __walk_process_mementry(self, kgsl_private_base_addr, dump,
                                format_str):
        pid = dump.read_structure_field(kgsl_private_base_addr,
                                        'struct kgsl_process_private', 'pid')
        upid_offset = dump.field_offset('struct pid', 'numbers')
        upid = dump.read_int(pid + upid_offset)

        comm_offset = dump.field_offset('struct kgsl_process_private', 'comm')
        pname = str(dump.read_cstring(kgsl_private_base_addr + comm_offset))
        if pname == '' or upid is None:
            return

        mem_idr_offset = dump.field_offset('struct kgsl_process_private',
                                           'mem_idr')
        mementry_rt = kgsl_private_base_addr + mem_idr_offset
        total_size = [0]

        try:
            self.rtw.walk_radix_tree(mementry_rt, self.__print_mementry_info,
                                     upid, pname, [True], total_size,
                                     format_str)
            self.writeln(format_str.format("", "", "", "",
                         str_convert_to_kb(total_size[0]), "", "", "", ""))
        except Exception:
            self.writeln("Ramdump has a corrupted mementry: pid: " + str(upid)
                         + " comm: " + pname)

    def __print_mementry_info(self, mementry_addr, pid, pname, print_header,
                              total_size, format_str):
        dump = self.ramdump
        memdesc_offset = dump.field_offset('struct kgsl_mem_entry', 'memdesc')
        kgsl_memdesc_address = mementry_addr + memdesc_offset

        size = dump.read_structure_field(kgsl_memdesc_address,
                                         'struct kgsl_memdesc', 'size')
        gpuaddr = dump.read_structure_field(kgsl_memdesc_address,
                                            'struct kgsl_memdesc', 'gpuaddr')
        idr_id = dump.read_structure_field(mementry_addr,
                                           'struct kgsl_mem_entry', 'id')
        mflags = dump.read_structure_field(kgsl_memdesc_address,
                                           'struct kgsl_memdesc', 'flags')
        map_count = dump.read_structure_field(mementry_addr,
                                              'struct kgsl_mem_entry',
                                              'map_count')
        flags = self.prepare_process_memdesc_flags(kgsl_memdesc_address,
                                                   map_count)
        mtype = ((mflags & KGSL_MEMTYPE_MASK) >> KGSL_MEMTYPE_SHIFT)
        try:
            usage = kgsl_memtype[mtype]
        except IndexError:
            usage = "unknown: " + str(mtype)
        pending_free = dump.read_structure_field(mementry_addr,
                                                 'struct kgsl_mem_entry',
                                                 'pending_free')
        priv = dump.read_structure_field(kgsl_memdesc_address,
                                         'struct kgsl_mem_entry',
                                         'priv')
        total_size[0] += size

        if print_header[0] is True:
            self.writeln(format_str.format(
                str(pid), pname, hex(idr_id), hex(kgsl_memdesc_address),
                str(size), hex(gpuaddr), str(flags), usage, str(pending_free),
                hex(priv)))
            # Set to False to skip printing pid and pname for the rest
            print_header[0] = False
        else:
            self.writeln(format_str.format(
                "", "", hex(idr_id), hex(kgsl_memdesc_address), str(size),
                hex(gpuaddr), str(flags), usage, str(pending_free), hex(priv)))

    '''
    Returns flag string with following legend:
    is_global|is_readonly|align|cachemode|is_cpu_mapped|mapped|is_secure|is_vbo
      g/-    |    -/w    |L/l/-| u/t/b/- |    p/-      |  Y/N |    s/-  |  v/-
    '''
    def prepare_process_memdesc_flags(self, memdesc_addr, map_count):
        dump = self.ramdump
        priv = dump.read_structure_field(memdesc_addr,
                                         'struct kgsl_memdesc', 'priv')
        mflags = dump.read_structure_field(memdesc_addr,
                                           'struct kgsl_memdesc', 'flags')
        flags = ['-'] * 8

        if bool(priv & KGSL_MEMDESC_GLOBAL):
            flags[0] = 'g'

        if not bool(mflags & KGSL_MEMFLAGS_GPUREADONLY):
            flags[1] = 'w'

        align = ((mflags & KGSL_MEMALIGN_MASK) >> KGSL_MEMALIGN_SHIFT)
        if align >= log2(PAGE_SIZE << 8):
            flags[2] = 'L'
        elif align >= log2(PAGE_SIZE << 4):
            flags[2] = 'l'

        cachemode = ((mflags & KGSL_CACHEMODE_MASK) >> KGSL_CACHEMODE_SHIFT)
        flags[3] = kgsl_cachemode[cachemode]

        if bool(mflags & KGSL_MEMFLAGS_USE_CPU_MAP):
            flags[4] = 'p'

        if bool(map_count):
            flags[5] = 'Y'
        else:
            flags[5] = 'N'

        if bool(priv & KGSL_MEMDESC_SECURE):
            flags[6] = 's'

        if bool(mflags & KGSL_MEMFLAGS_VBO):
            flags[7] = 'v'

        return ''.join(flags)

    def parse_features_data(self, dump):
        gpucore = dump.read_structure_field(self.devp,
                                            'struct adreno_device',
                                            'gpucore')
        features = dump.read_structure_field(gpucore,
                                             'struct adreno_gpu_core',
                                             'features')
        self.writeln('features: ' + strhex(features))
        enabled = []
        disabled = []
        features_list = ['ADRENO_SPTP_PC', 'ADRENO_CONTENT_PROTECTION',
                         'ADRENO_PREEMPTION', 'ADRENO_LM',
                         'ADRENO_CPZ_RETENTION', 'ADRENO_SOFT_FAULT_DETECT',
                         'ADRENO_IFPC', 'ADRENO_IOCOHERENT', 'ADRENO_ACD',
                         'ADRENO_COOP_RESET', 'ADRENO_DEPRECATED',
                         'ADRENO_APRIV', 'ADRENO_BCL', 'ADRENO_L3_VOTE',
                         'ADRENO_LPA', 'ADRENO_LSR', 'ADRENO_HW_FENCE',
                         'ADRENO_DMS', 'ADRENO_AQE', 'ADRENO_GMU_WARMBOOT',
                         'ADRENO_CLX', 'ADRENO_GMU_THERMAL_MITIGATION',
                         'ADRENO_GMU_BASED_DCVS', 'ADRENO_RT_HINT',
                         'ADRENO_DEFER_GMEM_ALLOC', 'ADRENO_GMU_MINBW',
                         'ADRENO_DCVS_PROFILE', ]

        for i, feature in enumerate(features_list):
            if (features >> i) & 1:
                enabled.append(feature)
            else:
                disabled.append(feature)

        enabled_features = ' '.join(enabled)
        disabled_features = ' '.join(disabled)
        self.writeln('Features enabled: ' + str(enabled_features))
        self.writeln('')
        self.writeln('Features disabled: ' + str(disabled_features))
        self.writeln('Last bit used for features is: ' +
                     str(len(features_list)-1))

    def parse_kgsl_data(self, dump):
        adreno_boolean_list = adreno_boolean_data + ['dcvs_profile_enabled']
        kgsl_generic_field = ['open_count', 'active_cnt', 'state',
                              'requested_state', 'speed_bin',
                              'reset_counter', ]
        adreno_generic_field = ['ft_policy', 'dcvs_tuning_mingap_lvl',
                                'dcvs_tuning_numbusy_lvl', 'ifpc_count', ]

        for kgsl_field in kgsl_generic_field:
            value = dump.read_structure_field(self.devp, 'struct kgsl_device',
                                              kgsl_field)
            self.writeln(f'{kgsl_field}: ' + str(value))

        for adreno_field in adreno_boolean_list:
            addr = dump.struct_field_addr(self.devp,
                                          'struct adreno_device', adreno_field)
            value = dump.read_bool(addr)
            self.writeln(f'{adreno_field}: ' + str(value))

        for adreno_field in adreno_generic_field:
            value = dump.read_structure_field(self.devp,
                                              'struct adreno_device',
                                              adreno_field)
            self.writeln(f'{adreno_field}: ' + str(value))

        kgsl_mmu = dump.struct_field_addr(self.devp, 'struct kgsl_device',
                                          'mmu')
        pfpolicy = dump.read_structure_field(kgsl_mmu, 'struct kgsl_mmu',
                                             'pfpolicy')
        cur_rb = dump.read_structure_field(self.devp,
                                           'struct adreno_device', 'cur_rb')
        next_rb = dump.read_structure_field(self.devp,
                                            'struct adreno_device', 'next_rb')
        prev_rb = dump.read_structure_field(self.devp,
                                            'struct adreno_device', 'prev_rb')
        cur_rb_id = dump.read_structure_field(cur_rb,
                                              'struct adreno_ringbuffer', 'id')
        next_rb_id = dump.read_structure_field(next_rb,
                                               'struct adreno_ringbuffer',
                                               'id')
        prev_rb_id = dump.read_structure_field(prev_rb,
                                               'struct adreno_ringbuffer',
                                               'id')
        firmware_offset = dump.field_offset('struct adreno_device', 'fw')
        cp_ucode_ver = dump.read_structure_field(self.devp + firmware_offset,
                                                 'struct adreno_firmware',
                                                 'version')
        host_based_dcvs_addr = dump.struct_field_addr(self.devp,
                                                      'struct kgsl_device',
                                                      'host_based_dcvs')
        host_based_dcvs = dump.read_bool(host_based_dcvs_addr)
        l3_vote_addr = dump.struct_field_addr(self.devp,
                                              'struct kgsl_device',
                                              'l3_vote')
        l3_vote = dump.read_bool(l3_vote_addr)

        self.writeln('l3_vote: ' + str(l3_vote))
        self.writeln('pfpolicy: ' + str(pfpolicy))
        self.writeln('cur_rb: ' + strhex(cur_rb))
        self.writeln('cur_rb_id: ' + str(cur_rb_id))
        self.writeln('next_rb: ' + strhex(next_rb))
        self.writeln('next_rb_id: ' + str(next_rb_id))
        self.writeln('prev_rb: ' + strhex(prev_rb))
        self.writeln('prev_rb_id: ' + str(prev_rb_id))
        self.writeln('CP ucode version: ' + strhex(cp_ucode_ver))
        self.writeln('host_based_dcvs: ' + str(host_based_dcvs))

    def parse_kgsl_mem(self, dump):
        page_alloc = dump.read('kgsl_driver.stats.page_alloc')
        coherent = dump.read('kgsl_driver.stats.coherent')
        secure = dump.read('kgsl_driver.stats.secure')

        self.writeln('KGSL Total: ' + str_convert_to_kb(secure +
                     page_alloc + coherent))
        self.writeln('\tsecure: ' + str_convert_to_kb(secure))
        self.writeln('\tnon-secure: ' + str_convert_to_kb(page_alloc +
                     coherent))
        self.writeln('\t\tpage_alloc: ' + str_convert_to_kb(page_alloc))
        self.writeln('\t\tcoherent: ' + str_convert_to_kb(coherent))

        pools_base_addr = dump.address_of('kgsl_pools')
        shift = dump.sizeof('struct kgsl_page_pool')
        pool_order = []
        pool_size = []
        order_offset = dump.field_offset('struct kgsl_page_pool', 'pool_order')
        page_count_offset = dump.field_offset('struct kgsl_page_pool',
                                              'page_count')
        for i in range(KGSL_MAX_POOLS):
            if pools_base_addr is None or order_offset is None:
                break
            p_order = dump.read_int(pools_base_addr + order_offset)
            pool_order.append(p_order)
            page_count = dump.read_int(pools_base_addr + page_count_offset)
            pool_size.append(page_count * (1 << p_order))
            pools_base_addr += shift

        self.writeln('\nKGSL Pool Size: ' +
                     str_convert_to_kb(sum(pool_size)*PAGE_SIZE))
        for i in range(len(pool_order)):
            self.writeln('\t' + str(pool_order[i]) + ' order pool size: ' +
                         str_convert_to_kb(pool_size[i]*PAGE_SIZE))

    def parse_eventlog_data(self, dump):
        parse_eventlog_buffer(self.writeln, dump)

    def parse_preempt_data(self, dump):
        preempt_addr = dump.struct_field_addr(self.devp,
                                              'struct adreno_device',
                                              'preempt')
        state = dump.read_structure_field(preempt_addr,
                                          'struct adreno_preemption', 'state')
        count = dump.read_structure_field(preempt_addr,
                                          'struct adreno_preemption', 'count')
        preempt_level = dump.read_structure_field(preempt_addr,
                                                  'struct adreno_preemption',
                                                  'preempt_level')

        self.writeln('state: ' + adreno_preempt_state[state])
        self.writeln('count: ' + str(count))
        self.writeln('preempt_level: ' + str(preempt_level))

    def parse_dispatcher_queues(self, arr_base, shift, queue_name):
        self.write(queue_name + ': ')
        active_jobs = False
        for i in range(16):
            first = self.ramdump.read_structure_field(
                                arr_base, 'struct llist_head', 'first')
            if first != 0:
                if not active_jobs:
                    self.writeln('')
                self.writeln('\t' + queue_name + '[' + str(i) +
                             '].first: ' + strhex(first))
                active_jobs = True
            arr_base += shift

        if not active_jobs:
            self.writeln('0x0')

    def parse_dispatcher_data(self, dump):
        dispatcher_addr = dump.struct_field_addr(self.devp,
                                                 'struct adreno_device',
                                                 'dispatcher')
        inflight = dump.read_structure_field(dispatcher_addr,
                                             'struct adreno_dispatcher',
                                             'inflight')
        jobs_base_addr = dump.struct_field_addr(dispatcher_addr,
                                                'struct adreno_dispatcher',
                                                'jobs')
        requeue_base_addr = dump.struct_field_addr(dispatcher_addr,
                                                   'struct adreno_dispatcher',
                                                   'requeue')
        fault_counter = dump.read_structure_field(dispatcher_addr,
                                                  'struct adreno_dispatcher',
                                                  'fault')

        self.writeln('inflight: ' + str(inflight))
        shift = dump.sizeof('struct llist_head')
        self.parse_dispatcher_queues(jobs_base_addr, shift, 'jobs')
        self.parse_dispatcher_queues(requeue_base_addr, shift, 'requeue')
        self.writeln('fault_counter: ' + str(fault_counter))

    def parse_rb_inflight_data(self, dump):
        rb_base_addr = dump.struct_field_addr(self.devp,
                                              'struct adreno_device',
                                              'ringbuffers')
        ringbuffers = []
        inflight_queue_result = []

        for i in range(0, KGSL_PRIORITY_MAX_RB_LEVELS):
            ringbuffers_temp = []
            rb_array_index_addr = dump.array_index(
                rb_base_addr, "struct adreno_ringbuffer", i)
            wptr = dump.read_structure_field(rb_array_index_addr,
                                             'struct adreno_ringbuffer',
                                             'wptr')
            _wptr = dump.read_structure_field(rb_array_index_addr,
                                              'struct adreno_ringbuffer',
                                              '_wptr')
            last_wptr = dump.read_structure_field(
                        rb_array_index_addr,
                        'struct adreno_ringbuffer', 'last_wptr')
            id = dump.read_structure_field(rb_array_index_addr,
                                           'struct adreno_ringbuffer', 'id')
            flags = dump.read_structure_field(rb_array_index_addr,
                                              'struct adreno_ringbuffer',
                                              'flags')

            drawctxt_active = dump.read_structure_field(
                rb_array_index_addr, 'struct adreno_ringbuffer',
                'drawctxt_active')

            if drawctxt_active != 0:
                kgsl_context_id = dump.read_structure_field(
                    drawctxt_active, 'struct kgsl_context', 'id')
                proc_priv_val = dump.read_structure_field(
                    drawctxt_active, 'struct kgsl_context', 'proc_priv')
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
            inflight = dump.read_structure_field(
                dispatch_q_address, 'struct adreno_dispatcher_drawqueue',
                'inflight')
            cmd_q_address = dispatch_q_address + dump.field_offset(
                'struct adreno_dispatcher_drawqueue', 'cmd_q')
            head = dump.read_structure_field(
                dispatch_q_address, 'struct adreno_dispatcher_drawqueue',
                'head')
            tail = dump.read_structure_field(
                dispatch_q_address, 'struct adreno_dispatcher_drawqueue',
                'tail')

            dispatcher_result = []
            while head is not tail:
                dispatcher_temp = []
                inflight_queue_index_address = dump.array_index(
                    cmd_q_address, 'struct kgsl_drawobj_cmd *', head)
                inflight_queue_index_value = dump.read_word(
                    inflight_queue_index_address)

                if inflight_queue_index_value != 0:
                    global_ts = dump.read_structure_field(
                        inflight_queue_index_value,
                        'struct kgsl_drawobj_cmd', 'global_ts')
                    fault_policy = dump.read_structure_field(
                        inflight_queue_index_value,
                        'struct kgsl_drawobj_cmd', 'fault_policy')
                    fault_recovery = dump.read_structure_field(
                        inflight_queue_index_value,
                        'struct kgsl_drawobj_cmd', 'fault_recovery')

                    base_address = inflight_queue_index_value + \
                        dump.field_offset('struct kgsl_drawobj_cmd', 'base')
                    drawobj_type = dump.read_structure_field(
                        base_address, 'struct kgsl_drawobj', 'type')
                    timestamp = dump.read_structure_field(
                        base_address, 'struct kgsl_drawobj', 'timestamp')
                    flags = dump.read_structure_field(
                        base_address, 'struct kgsl_drawobj', 'flags')
                    context_pointer = dump.read_pointer(dump.field_offset(
                        'struct kgsl_drawobj', 'context')+base_address)
                    context_id = dump.read_structure_field(
                        context_pointer, 'struct kgsl_context', 'id')
                    proc_priv = dump.read_structure_field(
                        context_pointer, 'struct kgsl_context', 'proc_priv')
                    pid = dump.read_structure_field(
                        proc_priv, 'struct kgsl_process_private', 'pid')
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

    def parse_pwrctrl_data(self, dump):
        pwrctrl_list = pwrctrl_data + ['rt_pwrlevel_hint']
        pwrctl_data_hex = ['power_flags', 'ctrl_flags']

        pwrctrl_address = dump.struct_field_addr(self.devp,
                                                 'struct kgsl_device',
                                                 'pwrctrl')
        bus_control_addr = dump.struct_field_addr(self.devp,
                                                  'struct kgsl_pwrctrl',
                                                  'bus_control')
        bus_control = dump.read_bool(bus_control_addr)
        self.writeln('pwrctrl_address:  ' + strhex(pwrctrl_address))
        self.writeln('bus_control: ' + str(bus_control))

        for data in pwrctrl_list:
            value = dump.read_structure_field(pwrctrl_address,
                                              'struct kgsl_pwrctrl', data)
            if data == 'num_pwrlevels':
                num_pwrlevels = value
            if data in pwrctl_data_hex:
                self.writeln(f'{data}: ' + strhex(value))
            else:
                self.writeln(f'{data}: ' + str(value))
        self.writeln()

        pwr_levels_result = []
        pwrlevels_base_address = pwrctrl_address + \
            dump.field_offset('struct kgsl_pwrctrl', 'pwrlevels')

        for i in range(0, num_pwrlevels):
            pwr_levels_temp = []
            pwrlevels_array_idx_addr = dump.array_index(
                pwrlevels_base_address, "struct kgsl_pwrlevel", i)
            gpu_freq = dump.read_structure_field(
                pwrlevels_array_idx_addr, 'struct kgsl_pwrlevel', 'gpu_freq')
            bus_freq = dump.read_structure_field(
                pwrlevels_array_idx_addr, 'struct kgsl_pwrlevel', 'bus_freq')
            bus_min = dump.read_structure_field(
                pwrlevels_array_idx_addr, 'struct kgsl_pwrlevel', 'bus_min')
            bus_max = dump.read_structure_field(
                pwrlevels_array_idx_addr, 'struct kgsl_pwrlevel', 'bus_max')
            acd_level = dump.read_structure_field(
                pwrlevels_array_idx_addr, 'struct kgsl_pwrlevel', 'acd_level')
            if acd_level is None:
                acd_level = 0
            pwr_levels_temp.append(pwrlevels_array_idx_addr)
            pwr_levels_temp.append(gpu_freq)
            pwr_levels_temp.append(bus_freq)
            pwr_levels_temp.append(bus_min)
            pwr_levels_temp.append(bus_max)
            pwr_levels_temp.append(acd_level)
            pwr_levels_result.append(pwr_levels_temp)

        self.writeln('pwrlevels_base_address:  '
                     + strhex(pwrlevels_base_address))
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

    def parse_mutex_data(self, dump):
        self.writeln("device_mutex:")
        device_mutex = dump.read_structure_field(self.devp,
                                                 'struct kgsl_device', 'mutex')
        dispatcher_mutex = dump.read_structure_field(self.devp,
                                                     'struct adreno_device',
                                                     'dispatcher')
        mutex_val = dump.read_word(device_mutex)

        if mutex_val:
            tgid = dump.read_structure_field(
                mutex_val, 'struct task_struct', 'tgid')
            comm_add = mutex_val + \
                dump.field_offset('struct task_struct', 'comm')
            comm_val = dump.read_cstring(comm_add)
            self.writeln("tgid: " + str(tgid))
            self.writeln("comm: " + comm_val)
        else:
            self.writeln("UNLOCKED")

        self.writeln()
        self.writeln("dispatcher_mutex:")
        dispatcher_mutex_val = dump.read_word(dispatcher_mutex)

        if dispatcher_mutex_val:
            tgid = dump.read_structure_field(
                dispatcher_mutex_val, 'struct task_struct', 'tgid')
            comm_add = dispatcher_mutex_val + \
                dump.field_offset('struct task_struct', 'comm')
            comm_val = dump.read_cstring(comm_add)
            self.writeln("tgid: " + str(tgid))
            self.writeln("comm: " + str(comm_val))
        else:
            self.writeln("UNLOCKED")

    def is_hwsched_enabled(self):
        dump = self.ramdump

        hwsched_addr = dump.struct_field_addr(self.devp,
                                              'struct adreno_device',
                                              'hwsched')
        hwsched_ops = dump.read_structure_field(hwsched_addr,
                                                'struct adreno_hwsched',
                                                'hwsched_ops')
        return bool(hwsched_ops)

    def get_scratch_memory_memdesc(self):
        dump = self.ramdump
        hwsched_enabled = self.is_hwsched_enabled()
        if not hwsched_enabled:
            scratch_obj = dump.read_structure_field(self.devp,
                                                    'struct kgsl_device',
                                                    'scratch')
            return scratch_obj

        gpucore = dump.read_structure_field(self.devp,
                                            'struct adreno_device', 'gpucore')
        gpurev = dump.read_structure_field(gpucore,
                                           'struct adreno_gpu_core', 'gpurev')
        if gpurev >= 0x80000:
            hwsched_device_struct = 'struct gen8_hwsched_device'
            hwsched_hfi_struct = 'struct gen8_hwsched_hfi'
            gmu_dev_addr = dump.sibling_field_addr(self.devp,
                                                   'struct gen8_device',
                                                   'adreno_dev', 'gmu')
        elif gpurev >= 0x70000:
            hwsched_device_struct = 'struct gen7_hwsched_device'
            hwsched_hfi_struct = 'struct gen7_hwsched_hfi'
            gmu_dev_addr = dump.sibling_field_addr(self.devp,
                                                   'struct gen7_device',
                                                   'adreno_dev', 'gmu')
        else:
            hwsched_device_struct = 'struct a6xx_hwsched_device'
            hwsched_hfi_struct = 'struct a6xx_hwsched_hfi'
            gmu_dev_addr = dump.sibling_field_addr(self.devp,
                                                   'struct a6xx_device',
                                                   'adreno_dev', 'gmu')
        try:
            hwsched_addr = dump.struct_field_addr(self.devp,
                                                  'struct adreno_device',
                                                  'hwsched')
            mem_alloc_entries = dump.read_structure_field(
                hwsched_addr, 'struct adreno_hwsched', 'mem_alloc_entries')

            if mem_alloc_entries is None:
                raise ValueError("mem_alloc_entries is None")
            mem_alloc_table_addr = dump.struct_field_addr(
                hwsched_addr, 'struct adreno_hwsched', 'mem_alloc_table')

        except Exception:
            hwsched_hfi = dump.struct_field_addr(
                gmu_dev_addr, hwsched_device_struct, 'hwsched_hfi'
            )
            mem_alloc_entries = dump.read_structure_field(
                hwsched_hfi, hwsched_hfi_struct, 'mem_alloc_entries')
            mem_alloc_table_addr = dump.struct_field_addr(
                hwsched_hfi, hwsched_hfi_struct, 'mem_alloc_table')

        if mem_alloc_entries is None:
            return None

        for i in range(mem_alloc_entries):
            mem_alloc_table_idx_addr = dump.array_index(
                mem_alloc_table_addr, "struct hfi_mem_alloc_entry",
                i)
            mem_kind = dump.read_structure_field(mem_alloc_table_idx_addr,
                                                 'struct hfi_mem_alloc_desc',
                                                 'mem_kind')
            if mem_kind == KGSL_HFI_MEMKIND_SCRATCH:
                scratch_obj = dump.read_structure_field(
                    mem_alloc_table_idx_addr, 'struct hfi_mem_alloc_entry',
                    'md')
                return scratch_obj
        return None

    def print_scratch_swsched(self, scratch):
        dump = self.ramdump

        # struct adreno_rb_shadow format string
        scratch_formatstr = '<IIIIQI'

        format_str = '{0:20} {1:20} {2:20} {3:20} {4:20} {5:20} {6:20}'
        self.writeln(format_str.format("Ringbuffer_Id", "RPTR_Value",
                                       "BV_RPTR_Value", "BV_TS_Value",
                                       "CUR_RB_PTNAME", "TTBR0", "CONTEXTIDR"))
        for rb_id in range(MAX_NUM_RBS):
            rptr, bv_rptr, bv_ts, current_rb_ptname, ttbr0, contextidr = \
                dump.read_string(scratch, scratch_formatstr)
            self.writeln(format_str.format(str(rb_id), str(rptr), str(bv_rptr),
                                           str(bv_ts), str(current_rb_ptname),
                                           strhex(ttbr0), str(contextidr)))
            scratch += struct.calcsize(scratch_formatstr)

    def print_scratch_hwsched(self, scratch):
        dump = self.ramdump

        # GMU FW struct RBScratch format string
        scratch_formatstr = '<' + 'I'*MAX_NUM_RBS*5
        scratch_data = dump.read_string(scratch, scratch_formatstr)

        rptr = scratch_data[:MAX_NUM_RBS]
        rptrBv = scratch_data[MAX_NUM_RBS:MAX_NUM_RBS*2]
        sop = scratch_data[MAX_NUM_RBS*2:MAX_NUM_RBS*3]
        eop = scratch_data[MAX_NUM_RBS*3:MAX_NUM_RBS*4]
        tsBv = scratch_data[MAX_NUM_RBS*4:]

        format_str = '{0:20} {1:20} {2:20} {3:20} {4:20} {5:20}'
        self.writeln(format_str.format("Ringbuffer_Id", "RPTR_Value",
                                       "BV_RPTR_Value", "BV_TS_Value",
                                       "SOP", "EOP"))
        for rb_id in range(MAX_NUM_RBS):
            self.writeln(format_str.format(str(rb_id), str(rptr[rb_id]),
                                           str(rptrBv[rb_id]),
                                           str(tsBv[rb_id]), str(sop[rb_id]),
                                           str(eop[rb_id])))

    def parse_scratch_memory(self, dump):
        scratch_obj = self.get_scratch_memory_memdesc()
        if not scratch_obj:
            self.write("Scratch memory not found!\n")
            return

        hostptr = dump.read_structure_field(scratch_obj, 'struct kgsl_memdesc',
                                            'hostptr')
        self.write("hostptr:  " + strhex(hostptr) + "\n")

        if self.is_hwsched_enabled():
            self.print_scratch_hwsched(hostptr)
        else:
            self.print_scratch_swsched(hostptr)

    def parse_vrb_info(self, dump):
        gpucore = dump.read_structure_field(self.devp,
                                            'struct adreno_device',
                                            'gpucore')
        gpurev = dump.read_structure_field(gpucore,
                                           'struct adreno_gpu_core',
                                           'gpurev')
        if gpurev >= 0x80000:
            gmu_device = 'struct gen8_gmu_device'
            gmu_dev_addr = dump.sibling_field_addr(self.devp,
                                                   'struct gen8_device',
                                                   'adreno_dev', 'gmu')
        elif gpurev >= 0x70000:
            gmu_device = 'struct gen7_gmu_device'
            gmu_dev_addr = dump.sibling_field_addr(self.devp,
                                                   'struct gen7_device',
                                                   'adreno_dev', 'gmu')
        else:
            gmu_device = 'struct a6xx_gmu_device'
            gmu_dev_addr = dump.sibling_field_addr(self.devp,
                                                   'struct a6xx_device',
                                                   'adreno_dev', 'gmu')

        vrb = dump.read_structure_field(gmu_dev_addr, gmu_device, 'vrb')
        hostptr = dump.read_structure_field(vrb,
                                            'struct kgsl_memdesc', 'hostptr')
        size = dump.read_structure_field(vrb,
                                         'struct kgsl_memdesc', 'size')
        gmuaddr = dump.read_structure_field(vrb,
                                            'struct kgsl_memdesc', 'gmuaddr')

        self.writeln("hostptr: " + strhex(hostptr))
        self.writeln("size: " + strhex(size))
        self.writeln("gmuaddr: " + strhex(gmuaddr))

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

    def parse_hwsched_info(self, dump):
        hwsched_addr = dump.struct_field_addr(self.devp,
                                              'struct adreno_device',
                                              'hwsched')
        flags = dump.read_structure_field(hwsched_addr,
                                          'struct adreno_hwsched',
                                          'flags')
        self.writeln('flags: ' + strhex(flags))
        for i, flag in enumerate(hwsched_flags_data):
            value = (flags >> i) & 1
            self.writeln(f'{flag}: ' + str(value))

    def parse_memstore_memory(self, dump):
        memstore_obj = dump.read_structure_field(self.devp,
                                                 'struct kgsl_device',
                                                 'memstore')
        hostptr = dump.read_structure_field(memstore_obj,
                                            'struct kgsl_memdesc', 'hostptr')
        size = dump.read_structure_field(memstore_obj,
                                         'struct kgsl_memdesc', 'size')
        parse_memstore_memory_common(dump, hostptr, size, self.writeln)

    def parse_fence_data(self, dump):
        context_idr = dump.struct_field_addr(self.devp,
                                             'struct kgsl_device',
                                             'context_idr')
        self.rtw.walk_radix_tree(context_idr, self.__print_fence_info)
        return

    def __print_fence_info(self, context_addr):
        dump = self.ramdump
        context_id = dump.read_structure_field(context_addr,
                                               'struct kgsl_context', 'id')
        ktimeline_offset = dump.field_offset('struct kgsl_context',
                                             'ktimeline')
        ktimeline_addr = dump.read_pointer(context_addr + ktimeline_offset)

        name_offset = dump.field_offset('struct kgsl_sync_timeline',
                                        'name')
        name_addr = ktimeline_addr + name_offset
        kgsl_sync_timeline_name = dump.read_cstring(name_addr)

        kgsl_sync_timeline_last_ts = dump.read_structure_field(
            ktimeline_addr, 'struct kgsl_sync_timeline',
            'last_timestamp')
        kgsl_sync_timeline_kref_counter = dump.read_byte(
            ktimeline_addr)

        self.writeln("context id: " + str(context_id))
        self.writeln("\t" + "kgsl_sync_timeline_name: "
                     + str(kgsl_sync_timeline_name))
        self.writeln("\t" + "kgsl_sync_timeline_last_timestamp: "
                     + str(kgsl_sync_timeline_last_ts))
        self.writeln("\t" + "kgsl_sync_timeline_kref_counter: "
                     + str(kgsl_sync_timeline_kref_counter))

    def parse_open_process_data(self, dump):
        format_str = '{0:10} {1:20} {2:20} {3:30} {4:20} {5:20} {6:10} ' \
                     '{7:20} {8:20}'
        self.writeln(format_str.format("PID", "PNAME", "PROCESS_PRIVATE_PTR",
                                       "KGSL_PAGETABLE_ADDRESS",
                                       "KGSL_CUR_MEMORY", "DMABUF_CUR_MEMORY",
                                       "CTX_CNT", "STATE", "CMDLINE STRING"))

        node_addr = dump.address_of('kgsl_driver') + dump.field_offset(
            'struct kgsl_driver', 'process_list')
        list_elem_offset = dump.field_offset(
                            'struct kgsl_process_private', 'list')
        open_process_list_walker = linux_list.ListWalker(
                                    dump, node_addr, list_elem_offset)
        open_process_list_walker.walk(self.walk_process_private,
                                      dump, format_str)

    def walk_process_private(self, kgsl_private_base_addr, dump, format_str):
        pid = dump.read_structure_field(
            kgsl_private_base_addr, 'struct kgsl_process_private', 'pid')
        upid_offset = dump.field_offset('struct pid', 'numbers')
        upid = dump.read_int(pid + upid_offset)

        comm_offset = dump.field_offset('struct kgsl_process_private', 'comm')
        pname = dump.read_cstring(kgsl_private_base_addr + comm_offset)
        if pname == '' or upid is None:
            return

        kgsl_pagetable_address = dump.read_structure_field(
            kgsl_private_base_addr, 'struct kgsl_process_private', 'pagetable')

        stats_offset = dump.field_offset('struct kgsl_process_private',
                                         'stats')
        stats_addr = kgsl_private_base_addr + stats_offset

        kgsl_mem = dump.read_slong(stats_addr)
        dmabuf_mem = dump.read_slong(stats_addr + (16 * 4))

        ctxt_count = dump.read_structure_field(kgsl_private_base_addr,
                                               'struct kgsl_process_private',
                                               'ctxt_count')
        state = dump.read_structure_field(kgsl_private_base_addr,
                                          'struct kgsl_process_private',
                                          'state')
        cmdline_offset = dump.field_offset('struct kgsl_process_private',
                                           'cmdline')
        cmdline_string = dump.read_cstring(dump.read_pointer(
                                           kgsl_private_base_addr +
                                           cmdline_offset))

        self.writeln(format_str.format(
            str(upid), str(pname), hex(kgsl_private_base_addr),
            hex(kgsl_pagetable_address), str_convert_to_kb(kgsl_mem),
            str_convert_to_kb(dmabuf_mem), str(ctxt_count),
            hex(state), str(cmdline_string)))

    def parse_pagetables(self, dump):
        format_str = '{0:14} {1:16} {2:20}'
        self.writeln(format_str.format("PID", "pt_base", "ttbr0"))
        node_addr = dump.address_of('kgsl_driver') + dump.field_offset(
            'struct kgsl_driver', 'pagetable_list')
        list_elem_offset = dump.field_offset(
                            'struct kgsl_pagetable', 'list')
        pagetable_list_walker = linux_list.ListWalker(
                                    dump, node_addr, list_elem_offset)
        pagetable_list_walker.walk(self.walk_pagetable,
                                   dump, format_str)

    def walk_pagetable(self, pt_base_addr, dump, format_str):
        pid = dump.read_structure_field(
            pt_base_addr, 'struct kgsl_pagetable', 'name')
        if pid == 0 or pid == 1:
            return

        iommu_pt_base_addr = dump.container_of(pt_base_addr,
                                               'struct kgsl_iommu_pt', 'base')
        ttbr0_mask = 0xFFFFFFFFFFFF
        ttbr0_val = dump.read_structure_field(iommu_pt_base_addr,
                                              'struct kgsl_iommu_pt', 'ttbr0')
        pt_base = ttbr0_val & ttbr0_mask

        self.writeln(format_str.format(
            str(pid), strhex(pt_base), strhex(ttbr0_val)))

    def parse_active_fences(self, dump):
        format_str = '{0:14} {1:16} {2:20}'
        self.writeln(format_str.format("ID", "timestamp", "index"))
        node_addr = dump.address_of('hw_fence_list')
        list_elem_offset = dump.field_offset(
                            'struct kgsl_sync_fence', 'hw_fence_list')
        fences_list_walker = linux_list.ListWalker(
                                    dump, node_addr, list_elem_offset)
        fences_list_walker.walk(self.walk_fences,
                                dump, format_str)

    def walk_fences(self, pt_base_addr, dump, format_str):
        id = dump.read_structure_field(
            pt_base_addr, 'struct kgsl_sync_fence', 'context_id')
        timestamp = dump.read_structure_field(
            pt_base_addr, 'struct kgsl_sync_fence', 'timestamp')
        hw_fence_index = dump.read_structure_field(
            pt_base_addr, 'struct kgsl_sync_fence', 'hw_fence_index')
        self.writeln(format_str.format(
            str(id), str(timestamp), str(hw_fence_index)))

    def parse_gmu_data(self, dump):
        gmu_core = dump.struct_field_addr(self.devp,
                                          'struct kgsl_device', 'gmu_core')
        gmu_on = dump.read_structure_field(gmu_core,
                                           'struct gmu_core_device', 'flags')
        if not ((gmu_on >> 4) & 1):
            self.writeln('GMU not enabled.')
            return

        gpucore = dump.read_structure_field(self.devp,
                                            'struct adreno_device',
                                            'gpucore')
        gpurev = dump.read_structure_field(gpucore,
                                           'struct adreno_gpu_core',
                                           'gpurev')
        if gpurev >= 0x80000:
            gmu_device = 'struct gen8_gmu_device'
            gmu_dev_addr = dump.sibling_field_addr(self.devp,
                                                   'struct gen8_device',
                                                   'adreno_dev', 'gmu')
        elif gpurev >= 0x70000:
            gmu_device = 'struct gen7_gmu_device'
            gmu_dev_addr = dump.sibling_field_addr(self.devp,
                                                   'struct gen7_device',
                                                   'adreno_dev', 'gmu')
        else:
            gmu_device = 'struct a6xx_gmu_device'
            gmu_dev_addr = dump.sibling_field_addr(self.devp,
                                                   'struct a6xx_device',
                                                   'adreno_dev', 'gmu')
            preall_addr = dump.struct_field_addr(gmu_dev_addr,
                                                 gmu_device, 'preallocations')
            preallocations = dump.read_bool(preall_addr)

        gmu_logs = dump.read_structure_field(gmu_dev_addr, gmu_device,
                                             'gmu_log')
        hostptr = dump.read_structure_field(gmu_logs,
                                            'struct kgsl_memdesc', 'hostptr')
        size = dump.read_structure_field(gmu_logs,
                                         'struct kgsl_memdesc', 'size')

        self.writeln('\nTrace Details:')
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

        log_stream_addr = dump.struct_field_addr(gmu_dev_addr,
                                                 gmu_device,
                                                 'log_stream_enable')
        log_stream_enable = dump.read_bool(log_stream_addr)

        gmu_fw_ver = dump.read_structure_field(gmu_core,
                                               'struct gmu_core_device',
                                               'ver.core')
        if gmu_fw_ver is None:
            gmu_fw_ver = dump.read_u32(gmu_dev_addr)

        pwr_fw_ver = dump.read_structure_field(gmu_core,
                                               'struct gmu_core_device',
                                               'ver.pwr')
        if pwr_fw_ver is None:
            pwr_fw_ver = dump.read_u32(gmu_dev_addr + 8)

        flags = dump.read_structure_field(gmu_dev_addr, gmu_device, 'flags')

        idle_level = dump.read_structure_field(gmu_dev_addr, gmu_device,
                                               'idle_level')

        global_entries = dump.read_structure_field(gmu_core,
                                                   'struct gmu_core_device',
                                                   'global_entries')
        if global_entries is None:
            global_entries = dump.read_structure_field(gmu_dev_addr,
                                                       gmu_device,
                                                       'global_entries')

        cm3_fault = dump.read_structure_field(gmu_dev_addr, gmu_device,
                                              'cm3_fault')
        warmboot_addr = dump.struct_field_addr(gmu_core,
                                               'struct gmu_core_device',
                                               'warmboot_enabled')
        warmboot_enable = dump.read_bool(warmboot_addr)

        self.writeln()
        self.writeln('GMU Firmware Version: ' + strhex(gmu_fw_ver))
        self.writeln('Power Firmware Version: ' + strhex(pwr_fw_ver))
        self.writeln()
        self.writeln('idle_level: ' + str(idle_level))
        self.writeln('internal gmu flags: ' + strhex(flags))
        self.writeln('global_entries: ' + str(global_entries))
        if gpurev < 0x70000:
            self.writeln('preallocations: ' + str(preallocations))
        self.writeln('log_stream_enable: ' + str(log_stream_enable))
        self.writeln('cm3_fault: ' + str(cm3_fault))
        self.writeln('warmboot_enable: ' + str(warmboot_enable))

        domain = dump.read_structure_field(gmu_core, 'struct gmu_core_device',
                                           'domain')
        if domain is None:
            domain = dump.read_structure_field(gmu_dev_addr,
                                               gmu_device, 'domain')
        arm_smmu = dump.container_of(domain,
                                     'struct arm_smmu_domain', 'domain')
        pgtbl_ops = dump.read_structure_field(arm_smmu,
                                              'struct arm_smmu_domain',
                                              'pgtbl_ops')

        if pgtbl_ops is not None:
            pgtbl_cfg = dump.sibling_field_addr(pgtbl_ops,
                                            'struct io_pgtable', 'ops', 'cfg')
            ttbr1_val = dump.read_structure_field(pgtbl_cfg,
                                              'struct io_pgtable_cfg',
                                              'arm_lpae_s1_cfg.ttbr')
            self.writeln('ttbr1: ' + strhex(ttbr1_val))

        num_clks = dump.read_structure_field(gmu_dev_addr, gmu_device,
                                             'num_clks')
        clks = dump.read_structure_field(gmu_dev_addr, gmu_device, 'clks')
        clk_id_addr = dump.read_structure_field(clks,
                                                'struct clk_bulk_data', 'id')
        clk_id = dump.read_cstring(clk_id_addr)

        self.writeln('num_clks: ' + str(num_clks))
        self.writeln('clock consumer ID: ' + str(clk_id))

    def dump_gpu_snapshot(self, dump):
        snapshot_faultcount = dump.read_structure_field(self.devp,
                                                        'struct kgsl_device',
                                                        'snapshot_faultcount')
        self.writeln(str(snapshot_faultcount) + ' snapshot fault(s) detected.')

        force_panic_addr = dump.struct_field_addr(self.devp,
                                                  'struct kgsl_device',
                                                  'force_panic')
        force_panic = dump.read_bool(force_panic_addr)
        gmu_core_addr = dump.struct_field_addr(self.devp,
                                               'struct kgsl_device',
                                               'gmu_core')
        gf_panic = dump.read_structure_field(gmu_core_addr,
                                             'struct gmu_core_device',
                                             'gf_panic')
        self.writeln('force_panic: ' + str(force_panic))
        self.writeln('gf_panic: ' + str(gf_panic))

        if snapshot_faultcount == 0:
            self.writeln('No GPU hang, skipping snapshot dumping.')
            return

        snapshot_offset = dump.field_offset('struct kgsl_device', 'snapshot')
        snapshot_memory_offset = dump.field_offset('struct kgsl_device',
                                                   'snapshot_memory')
        snapshot_memory_size = dump.read_u32(self.devp +
                                             snapshot_memory_offset +
                                             dump.sizeof('void *') +
                                             dump.sizeof('dma_addr_t'))
        snapshot_base_addr = dump.read_pointer(self.devp + snapshot_offset)

        if snapshot_base_addr == 0:
            snapshot_memory_ptr = dump.read_pointer(self.devp +
                                                    snapshot_memory_offset)
            if snapshot_memory_ptr is None or snapshot_memory_ptr == 0:
                self.writeln('Snapshot not found.')
                return
            file_name = 'gpu_snapshot_memory.bpmd'
            file = self.ramdump.open_file('gpu_parser/' + file_name, 'wb')
            self.write('Snapshot start not found, ')
            self.writeln('dumping entire region to ' + file_name)
            data = self.ramdump.read_binarystring(snapshot_memory_ptr,
                                                  snapshot_memory_size)
            file.write(data)
            file.close()
            return

        snapshot_start = dump.read_structure_field(
            snapshot_base_addr, 'struct kgsl_snapshot', 'start')
        snapshot_size = dump.read_structure_field(
            snapshot_base_addr, 'struct kgsl_snapshot', 'size')
        snapshot_timestamp = dump.read_structure_field(
            snapshot_base_addr, 'struct kgsl_snapshot', 'timestamp')
        snapshot_process_offset = dump.field_offset('struct kgsl_snapshot',
                                                    'process')
        snapshot_process = dump.read_pointer(snapshot_base_addr +
                                             snapshot_process_offset)
        snapshot_pid = dump.read_structure_field(
            snapshot_process, 'struct kgsl_process_private', 'pid')

        self.writeln('Snapshot Details:')
        self.writeln('\tStart Address: ' + strhex(snapshot_start))
        self.writeln('\tSize: ' + str_convert_to_kb(snapshot_size))
        self.writeln('\tTimestamp: ' + str(snapshot_timestamp))
        self.writeln('\tProcess PID: ' + str(snapshot_pid))

        file_name = 'gpu_snapshot_' + str(snapshot_timestamp) + '.bpmd'
        file = self.ramdump.open_file('gpu_parser/' + file_name, 'wb')

        if snapshot_size == 0:
            self.write('Snapshot freeze not completed.')
            self.writeln('Dumping entire region to ' + file_name)
            data = self.ramdump.read_binarystring(snapshot_start,
                                                  snapshot_memory_size)
        else:
            self.writeln('\nDumping ' + str_convert_to_kb(snapshot_size) +
                         ' starting from ' + strhex(snapshot_start) +
                         ' to ' + file_name)
            data = self.ramdump.read_binarystring(snapshot_start,
                                                  snapshot_size)
        file.write(data)
        file.close()

        extract_gmu_mem_from_snapshot(dump, "gpu_parser/" + file_name)
        generate_gmu_t32_files(dump)

    def dump_atomic_snapshot(self, dump):
        atomic_snapshot_addr = dump.struct_field_addr(self.devp,
                                                      'struct kgsl_device',
                                                      'snapshot_atomic')
        atomic_snapshot = dump.read_bool(atomic_snapshot_addr)
        if not atomic_snapshot:
            self.writeln('No atomic snapshot detected.')
            self.create_mini_snapshot(dump)
            return

        atomic_snapshot_offset = dump.field_offset(
            'struct kgsl_device', 'snapshot_memory_atomic')
        atomic_snapshot_base = dump.read_pointer(self.devp +
                                                 atomic_snapshot_offset)
        atomic_snapshot_size = dump.read_u32(self.devp +
                                             atomic_snapshot_offset + 8)

        if atomic_snapshot_base == 0 or atomic_snapshot_size == 0:
            self.writeln('Invalid atomic snapshot.')
            self.create_mini_snapshot(dump)
            return

        self.writeln('Atomic Snapshot Details:')
        self.writeln('\tStart Address: ' + strhex(atomic_snapshot_base))
        self.writeln('\tSize: ' + str_convert_to_kb(atomic_snapshot_size))

        file = self.ramdump.open_file('gpu_parser/atomic_snapshot.bpmd', 'wb')
        data = self.ramdump.read_binarystring(atomic_snapshot_base,
                                              atomic_snapshot_size)
        self.writeln('\nData dumped to atomic_snapshot.bpmd')
        file.write(data)
        file.close()

    def create_mini_snapshot(self, dump):
        create_snapshot_from_ramdump(self.devp, dump)

    def parse_gpu_dcvs_data(self, dump):
        state = dump.read_structure_field(self.devp,
                                          'struct kgsl_device', 'state')

        # Skip dumping and extraction of the DCVS data if GPU is not
        # in active state.
        if state == 2:
            adreno_tz_data_addr = dump.address_of('adreno_tz_data')

            bin_addr = dump.struct_field_addr(
                adreno_tz_data_addr, 'struct devfreq_msm_adreno_tz_data',
                'bin')
            total_time = dump.read_s64(bin_addr)
            busy_time = dump.read_s64(bin_addr + 8)

            bus_addr = dump.struct_field_addr(
                adreno_tz_data_addr, 'struct devfreq_msm_adreno_tz_data',
                'bus')
            ram_time = dump.read_u64(bus_addr + 8)
            ram_wait = dump.read_u64(bus_addr + 16)

            mod_percent = dump.read_structure_field(
                adreno_tz_data_addr, 'struct devfreq_msm_adreno_tz_data',
                'mod_percent')

            self.writeln("total_time: " + str(total_time))
            self.writeln("busy_time: " + str(busy_time))
            self.writeln("ram_time: " + str(ram_time))
            self.writeln("ram_wait: " + str(ram_wait))
            self.writeln("mod_percent: " + str(mod_percent))
        else:
            self.writeln("DCVS data dump skipped if GPU state is not ACTIVE")

    def parse_non_context_data(self, dump):
        gpucore = dump.read_structure_field(self.devp,
                                            'struct adreno_device',
                                            'gpucore')
        gpurev = dump.read_structure_field(gpucore,
                                           'struct adreno_gpu_core',
                                           'gpurev')
        if gpurev < 0x80000:
            return

        gmu_dev_addr = dump.sibling_field_addr(self.devp,
                                               'struct gen8_device',
                                               'adreno_dev', 'gmu')

        format_str = '{0:16} {1:16} {2:16} {3:16} {4:16}'
        self.writeln(format_str.format("offset", "pipelines", "value",
                                       "set", "list_type"))

        nc_overrides_addr = dump.read_structure_field(gmu_dev_addr,
                                                      'struct gen8_device',
                                                      'nc_overrides')
        struct_size = self.ramdump.sizeof('struct gen8_nonctxt_overrides')
        while(1):
            offset = dump.read_structure_field(nc_overrides_addr,
                                               'struct gen8_nonctxt_overrides',
                                               'offset')
            if offset == 0:
                return
            pipelines = dump.read_structure_field(
                nc_overrides_addr, 'struct gen8_nonctxt_overrides',
                'pipelines')
            value = dump.read_structure_field(nc_overrides_addr,
                                              'struct gen8_nonctxt_overrides',
                                              'val')
            addr = dump.struct_field_addr(nc_overrides_addr,
                                          'struct gen8_nonctxt_overrides',
                                          'set')
            set = dump.read_bool(addr)
            list_type = dump.read_structure_field(
                nc_overrides_addr, 'struct gen8_nonctxt_overrides',
                'list_type')
            self.writeln(format_str.format(strhex(offset), strhex(pipelines),
                         strhex(value), str(set), strhex(list_type)))
            nc_overrides_addr = nc_overrides_addr + struct_size
