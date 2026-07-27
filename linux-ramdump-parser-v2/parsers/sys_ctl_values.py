#Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
#SPDX-License-Identifier: GPL-2.0-only

import os
import re
import sys
import argparse
import csv
import shutil

import struct
from print_out import print_out_str,out_file
from ramdump import RamDump
from parser_util import register_parser, RamParser, cleanupString
import linux_list as llist

'''
/proc/sys/vm # ls
admin_reserve_kbytes         dirtytime_expire_seconds  mmap_rnd_bits             percpu_pagelist_high_fraction
compact_memory               drop_caches               mmap_rnd_compat_bits      stat_interval
compact_unevictable_allowed  extfrag_threshold         oom_dump_tasks            stat_refresh
compaction_proactiveness     laptop_mode               oom_kill_allocating_task  swappiness
dirty_background_bytes       legacy_va_layout          overcommit_kbytes         unprivileged_userfaultfd
dirty_background_ratio       lowmem_reserve_ratio      overcommit_memory         user_reserve_kbytes
dirty_bytes                  max_map_count             overcommit_ratio          vfs_cache_pressure
dirty_expire_centisecs       mem_profiling             page-cluster              watermark_boost_factor
dirty_ratio                  min_free_kbytes           page_lock_unfairness      watermark_scale_factor
dirty_writeback_centisecs    mmap_min_addr             panic_on_oom
'''

@register_parser('--sys_ctl_value', 'print sys_ctl_value information')
class sys_ctl_value(RamParser):

    def __init__(self, *args):
        super(sys_ctl_value, self).__init__(*args)

    def get_sys_ctl_by_name(self, sys_ctl_name, fout):
        value = None
        try:
            addr = self.ramdump.address_of(sys_ctl_name)
            value = self.ramdump.read_int(addr)
            print("%-32s   %16d" % (sys_ctl_name, value), file = fout)
        except Exception as e:
            print_out_str("error when get {0}: {1}".format(sys_ctl_name, str(e)))
        return value

    def get_zone_name(self, zone):
        zone_name_offset = self.ramdump.field_offset('struct zone', 'name')
        zname_addr = self.ramdump.read_word(zone + zone_name_offset)
        zname = self.ramdump.read_cstring(zname_addr, 12)
        return zname

    def parse(self):
        with self.ramdump.open_file('sys_ctl.txt') as self.fout:
            self.get_sys_ctl_by_name('sysctl_vfs_cache_pressure', self.fout)
            self.get_sys_ctl_by_name('dirtytime_expire_interval', self.fout)
            self.get_sys_ctl_by_name('dirty_expire_interval', self.fout)
            self.get_sys_ctl_by_name('dirty_background_bytes', self.fout)
            self.get_sys_ctl_by_name('dirty_background_ratio', self.fout)
            self.get_sys_ctl_by_name('dirty_expire_centisecs', self.fout)
            self.get_sys_ctl_by_name('dirty_writeback_interval', self.fout)

            self.get_sys_ctl_by_name('vm_dirty_ratio', self.fout)
            self.get_sys_ctl_by_name('vm_dirty_bytes', self.fout)

            self.get_sys_ctl_by_name('min_free_kbytes', self.fout)
            self.get_sys_ctl_by_name('watermark_boost_factor', self.fout)
            self.get_sys_ctl_by_name('watermark_scale_factor', self.fout)
            self.get_sys_ctl_by_name('sysctl_panic_on_oom', self.fout)
            self.get_sys_ctl_by_name('sysctl_oom_kill_allocating_task', self.fout)
            self.get_sys_ctl_by_name('sysctl_oom_dump_tasks', self.fout)

            self.get_sys_ctl_by_name('sysctl_extfrag_threshold', self.fout)
            self.get_sys_ctl_by_name('vm_swappiness', self.fout)

            max_nr_zones = self.ramdump.gdbmi.get_value_of('__MAX_NR_ZONES')
            contig_page_data = self.ramdump.address_of('contig_page_data')

            sizeofzone = self.ramdump.sizeof('struct zone')
            node_zones_offset = self.ramdump.field_offset(
                    'struct pglist_data', 'node_zones')
            zone = contig_page_data + node_zones_offset
            addr = self.ramdump.address_of('sysctl_lowmem_reserve_ratio')

            print("\n/proc/sys/vm/lowmem_reserve_ratio\n", file = self.fout)

            zone_names = ''
            ratios = ''
            for j in range(0, max_nr_zones):
                try:
                    value = self.ramdump.read_int(self.ramdump.array_index(addr, 'int', j))
                    zone_name = self.get_zone_name(zone)
                    zone_names += "{0:>16s}\t".format(zone_name)
                    ratios += "{0:>16d}\t".format(value)
                except Exception as e:
                    print_out_str("Error reading lowmem_reserve_ratio[{0}]: {1}".format(j, str(e)))
                    print("%16s " % ("ERROR"), end='', file = self.fout)
                zone = zone + sizeofzone

            print("%s \n" % (zone_names), file = self.fout)
            print("%s \n" % (ratios), file = self.fout)
