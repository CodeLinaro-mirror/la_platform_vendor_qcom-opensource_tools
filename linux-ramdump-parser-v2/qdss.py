# Copyright (c) 2012, 2014-2018, 2020-2021 The Linux Foundation. All rights reserved.
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

import struct
import itertools
import linux_list as llist
import ctypes
import re
import os
import html as _html
from print_out import print_out_str
from iommulib import IommuLib, MSM_SMMU_DOMAIN, MSM_SMMU_AARCH64_DOMAIN, ARM_SMMU_DOMAIN
from aarch64iommulib import create_flat_mappings, create_collapsed_mapping
from ramdump import Struct
from struct_print import struct_print_class

tmc_registers = {
    'RSZ': (0x004, 'RAM Size'),
    'STS': (0x00C, 'Status Register'),
    'RRD': (0x010, 'RAM Read Data Register'),
    'RRP': (0x014, 'RAM Read Pointer Register'),
    'RWP': (0x018, 'RAM Write Pointer Register'),
    'TRG': (0x01C, 'Trigger Counter Register'),
    'CTL': (0x020, 'Control Register'),
    'RWD': (0x024, 'RAM Write Data Register'),
    'MODE': (0x028, 'Mode Register'),
    'LBUFLEVEL': (0x02C, 'Latched Buffer Fill Level'),
    'CBUFLEVEL': (0x030, 'Current Buffer Fill Level'),
    'BUFWM': (0x034, 'Buffer Level Water Mark'),
    'RRPHI': (0x038, 'RAM Read Pointer High Register'),
    'RWPHI': (0x03C, 'RAM Write Pointer High Register'),
    'AXICTL': (0x110, 'AXI Control Register'),
    'DBALO': (0x118, 'Data Buffer Address Low Register'),
    'DBAHI': (0x11C, 'Data Buffer Address High Register'),
    'FFSR': (0x300, 'Formatter and Flush Status Register'),
    'FFCR': (0x304, 'Formatter and Flush Control Register'),
    'PSCR': (0x308, 'Periodic Synchronization Counter Register'),
    'ITATBMDATA0': (0xED0, 'Integration Test ATB Master Data Register 0'),
    'ITATBMCTR2': (0xED4, 'Integration Test ATB Master Interface Control 2 Register'),
    'ITATBMCTR1': (0xED8, 'Integration Test ATB Master Control Register 1'),
    'ITATBMCTR0': (0xEDC, 'Integration Test ATB Master Interface Control 0 Register'),
    'ITMISCOP0': (0xEE0, 'Integration Test Miscellaneous Output Register 0'),
    'ITTRFLIN': (0xEE8, 'Integration Test Trigger In and Flush In Register'),
    'ITATBDATA0': (0xEEC, 'Integration Test ATB Data Register 0'),
    'ITATBCTR2': (0xEF0, 'Integration Test ATB Control 2 Register'),
    'ITATBCTR1': (0xEF4, 'Integration Test ATB Control 1 Register'),
    'ITATBCTR0': (0xEF8, 'Integration Test ATB Control 0 Register'),
    'ITCTRL': (0xF00, 'Integration Mode Control Register'),
    'CLAIMSET': (0xFA0, 'Claim Tag Set Register'),
    'CLAIMCLR': (0xFA4, 'Claim Tag Clear Register'),
    'LAR': (0xFB0, 'Lock Access Register'),
    'LSR': (0xFB4, 'Lock Status Register'),
    'AUTHSTATUS': (0xFB8, 'Authentication Status Register'),
    'DEVID': (0xFC8, 'Device Configuration Register'),
    'DEVTYPE': (0xFCC, 'Device Type Identifier Register'),
    'PERIPHID4': (0xFD0, 'Peripheral ID4 Register'),
    'PERIPHID5': (0xFD4, 'Peripheral ID5 Register'),
    'PERIPHID6': (0xFD8, 'Peripheral ID6 Register'),
    'PERIPHID7': (0xFDC, 'Peripheral ID7 Register'),
    'PERIPHID0': (0xFE0, 'Peripheral ID0 Register'),
    'PERIPHID1': (0xFE4, 'Peripheral ID1 Register'),
    'PERIPHID2': (0xFE8, 'Peripheral ID2 Register'),
    'PERIPHID3': (0xFEC, 'Peripheral ID3 Register'),
    'COMPID0': (0xFF0, 'Component ID0 Register'),
    'COMPID1': (0xFF4, 'Component ID1 Register'),
    'COMPID2': (0xFF8, 'Component ID2 Register'),
    'COMPID3': (0xFFC, 'Component ID3 Register'),
}

etm_registers = {
    'ETMCR': (0x000, 'Main Control Register'),
    'ETMCCR': (0x001, 'Configuration Code Register'),
    'ETMTRIGGER': (0x002, 'Trigger Event Register'),
    'ETMSR': (0x004, 'Status Register'),
    'ETMCSR': (0x005, 'System Configuration Register'),
    'ETMTSSCR': (0x006, 'TraceEnable Start/Stop Control Register'),
    'ETMTEEVR': (0x008, 'TraceEnable Event Register'),
    'ETMTECR1': (0x009, 'TraceEnable Control Register'),
    'ETMFFLR': (0x00B, 'FIFOFULL Level Register'),
    'ETMACVR0': (0x10, 'Address Comparator Value Register 0'),
    'ETMACVR1': (0x11, 'Address Comparator Value Register 1'),
    'ETMACVR2': (0x12, 'Address Comparator Value Register 2'),
    'ETMACVR3': (0x13, 'Address Comparator Value Register 3'),
    'ETMACVR4': (0x14, 'Address Comparator Value Register 4'),
    'ETMACVR5': (0x15, 'Address Comparator Value Register 5'),
    'ETMACVR6': (0x16, 'Address Comparator Value Register 6'),
    'ETMACVR7': (0x17, 'Address Comparator Value Register 7'),
    'ETMACVR8': (0x18, 'Address Comparator Value Register 8'),
    'ETMACVR9': (0x19, 'Address Comparator Value Register 9'),
    'ETMACVRA': (0x1A, 'Address Comparator Value Register A'),
    'ETMACVRB': (0x1B, 'Address Comparator Value Register B'),
    'ETMACVRC': (0x1C, 'Address Comparator Value Register C'),
    'ETMACVRD': (0x1D, 'Address Comparator Value Register D'),
    'ETMACVRE': (0x1E, 'Address Comparator Value Register E'),
    'ETMACVRF': (0x1F, 'Address Comparator Value Register F'),

    'ETMACVT0': (0x20, 'Address Comparator Type Register 0'),
    'ETMACVT1': (0x21, 'Address Comparator Type Register 1'),
    'ETMACVT2': (0x22, 'Address Comparator Type Register 2'),
    'ETMACVT3': (0x23, 'Address Comparator Type Register 3'),
    'ETMACVT4': (0x24, 'Address Comparator Type Register 4'),
    'ETMACVT5': (0x25, 'Address Comparator Type Register 5'),
    'ETMACVT6': (0x26, 'Address Comparator Type Register 6'),
    'ETMACVT7': (0x27, 'Address Comparator Type Register 7'),
    'ETMACVT8': (0x28, 'Address Comparator Type Register 8'),
    'ETMACVT9': (0x29, 'Address Comparator Type Register 9'),
    'ETMACVTA': (0x2A, 'Address Comparator Type Register A'),
    'ETMACVTB': (0x2B, 'Address Comparator Type Register B'),
    'ETMACVTC': (0x2C, 'Address Comparator Type Register C'),
    'ETMACVTD': (0x2D, 'Address Comparator Type Register D'),
    'ETMACVTE': (0x2E, 'Address Comparator Type Register E'),
    'ETMACVTF': (0x2F, 'Address Comparator Type Register F'),

    'ETMCNTRLDVR0': (0x050, 'Counter Reload Value Register 0'),
    'ETMCNTRLDVR1': (0x051, 'Counter Reload Value Register 1'),
    'ETMCNTRLDVR2': (0x052, 'Counter Reload Value Register 2'),
    'ETMCNTRLDVR3': (0x053, 'Counter Reload Value Register 3'),

    'ETMCNTRENR0': (0x054, 'Counter Enable Event Register 0'),
    'ETMCNTRENR1': (0x055, 'Counter Enable Event Register 1'),
    'ETMCNTRENR2': (0x056, 'Counter Enable Event Register 2'),
    'ETMCNTRENR3': (0x057, 'Counter Enable Event Register 3'),

    'ETMCNTRLDEVR0': (0x058, 'Counter Reload Event Registers 0'),
    'ETMCNTRLDEVR1': (0x059, 'Counter Reload Event Registers 1'),
    'ETMCNTRLDEVR2': (0x05A, 'Counter Reload Event Registers 2'),
    'ETMCNTRLDEVR3': (0x05B, 'Counter Reload Event Registers 3'),

    'ETMCNTVR0': (0x05C, 'Counter Value Register 0'),
    'ETMCNTVR1': (0x05D, 'Counter Value Register 1'),
    'ETMCNTVR2': (0x05E, 'Counter Value Register 2'),
    'ETMCNTVR3': (0x05F, 'Counter Value Register 3'),

    'ETMSQabEVR0': (0x060, 'Sequencer State Transition Event Register 0'),
    'ETMSQabEVR1': (0x061, 'Sequencer State Transition Event Register 1'),
    'ETMSQabEVR2': (0x062, 'Sequencer State Transition Event Register 2'),
    'ETMSQabEVR3': (0x063, 'Sequencer State Transition Event Register 3'),
    'ETMSQabEVR4': (0x064, 'Sequencer State Transition Event Register 4'),
    'ETMSQabEVR5': (0x065, 'Sequencer State Transition Event Register 5'),

    'ETMSQR': (0x067, 'Current Sequencer State Register'),

    'ETMEXTOUTEVR0': (0x068, 'External Output Event Registers 0'),
    'ETMEXTOUTEVR1': (0x069, 'External Output Event Registers 1'),
    'ETMEXTOUTEVR2': (0x06A, 'External Output Event Registers 2'),
    'ETMEXTOUTEVR3': (0x06B, 'External Output Event Registers 3'),

    'ETMCIDCVR0': (0x06C, 'Context ID Comparator Value Register 0'),
    'ETMCIDCVR1': (0x06D, 'Context ID Comparator Value Register 1'),
    'ETMCIDCVR2': (0x06E, 'Context ID Comparator Value Register 2'),

    'ETMCIDCMR0': (0x06F, 'Context ID Mask Register'),

    'ETMIMPSPEC0': (0x070, 'Implementation Specific Register 0'),
    'ETMIMPSPEC1': (0x071, 'Implementation Specific Register 1'),
    'ETMIMPSPEC2': (0x072, 'Implementation Specific Register 2'),
    'ETMIMPSPEC3': (0x073, 'Implementation Specific Register 3'),
    'ETMIMPSPEC4': (0x074, 'Implementation Specific Register 4'),
    'ETMIMPSPEC5': (0x075, 'Implementation Specific Register 5'),
    'ETMIMPSPEC6': (0x076, 'Implementation Specific Register 6'),
    'ETMIMPSPEC7': (0x077, 'Implementation Specific Register 7'),

    'ETMSYNCFR': (0x078, 'Synchronization Frequency Register'),
    'ETMIDR': (0x079, 'ID register'),
    'ETMCCER': (0x07A, 'Configuration Code Extension Register'),
    'ETMEXTINSELR': (0x07B, 'Extended External Input Selection Register'),
    'ETMTESSEICR': (0x07C, 'TraceEnable Start/Stop EmbeddedICE Control Register'),
    'ETMEIBCR': (0x07D, 'EmbeddedICE Behavior COntrol Register'),
    'ETMTSEVR': (0x07E, 'Timestamp Event Register'),
    'ETMAUXCR': (0x07F, 'Auxilary Control Register'),
    'ETMTRACEIDR': (0x080, 'CoreSight Trace ID Register'),
    'ETMVMIDCVR': (0x090, 'VMID Comparator Value Register'),

    'ETMOSLAR': (0x0C0, 'OS Lock Access Register'),
    'ETMOSLSR': (0x0C1, 'OS Lock Status Register'),
    'ETMPDCR': (0x0C4, 'Device Power-DOwn Control Register'),
    'ETMPDSR': (0x0C5, 'Device Power Down Status Register'),

    'ETMITCTRL': (0x3C0, 'Integration Mode Control Register'),
    'ETMCLAIMSET': (0x3E8, 'Claim Tag Set Register'),
    'ETMCLAIMCLR': (0x3E9, 'Claim Tag Clear Register'),
    'ETMLAR': (0x3Ec, 'Lock Access Register'),
    'ETMLSR': (0x3ED, 'Lock Status Register'),
    'ETMAUTHSTATUS': (0x3EE, 'Authentication Status Register'),
    'ETMDEVID': (0x3F2, 'Device Configuration Register'),
    'ETMDEVTYPE': (0x3F3, 'Device Type Register'),
    'ETMPIDR4': (0x3F4, 'Peripheral ID4 Register'),
    'ETMPIDR0': (0x3F8, 'Peripheral ID0 Register'),
    'ETMPIDR1': (0x3F9, 'Peripheral ID1 Register'),
    'ETMPIDR2': (0x3FA, 'Peripheral ID2 Register'),
    'ETMPIDR3': (0x3FB, 'Peripheral ID3 Register'),
    'ETMCIDR0': (0x3FC, 'Component ID0 Register'),
    'ETMCIDR1': (0x3FD, 'Component ID1 Register'),
    'ETMCIDR2': (0x3FE, 'Component ID2 Register'),
}

dbgui_registers = {
    'DBGUI_SECURE' : (0x000, 'Secure Register'),
    'DBGUI_CTL' : (0x004, 'Clear Register'),
    'DBGUI_CTL_MASK' : (0x008, 'CTL Mask Register'),
    'DBGUI_SWTRIG' : (0x00C, 'Software Trigger Register'),
    'DBGUI_STATUS' : (0x010, 'Status Register Register'),
    'DBGUI_HWE_MASK' : (0x014, 'Hardware Event Mask Register'),
    'DBGUI_CTR_VAL' : (0x018, 'Timeout Counter Terminal Value Register'),
    'DBGUI_CTR_EN' : (0x01C, 'Timeout Counter Enable Register'),
    'DBGUI_NUM_REGS_RD' : (0x020, 'Number of Register Read Control Register'),
    'DBGUI_ATB_REG' : (0x024, 'ATB Configuration Register'),
}

driver_types = [
    ('coresight-stm', 'parse_single_atid'),
    ('coresight-tpdm', 'parse_single_atid'),
    ('coresight-remote-etm', 'parse_remote_etm_atid'),
    ('coresight-etm4x', 'parse_single_atid'),
    ('coresight-dummy', 'parse_single_atid'),
    ('coresight-uetm', 'parse_uetm_atid'),
]

driver_structs = [
    ('coresight-stm', 'struct stm_drvdata'),
    ('coresight-tpdm', 'struct tpdm_drvdata'),
    ('coresight-remote-etm', 'struct remote_etm_drvdata'),
    ('coresight-etm4x', 'struct etmv4_drvdata'),
    ('coresight-dummy', 'struct dummy_drvdata'),
    ('coresight-uetm', 'struct uetm_drvdata'),
]

# Use a list of candidate field names to handle renames across kernel versions
qdss_atid_fields = [
    ('coresight-stm', ['traceid', 'trcid']),
    ('coresight-tpdm', ['traceid', 'trcid']),
    ('coresight-remote-etm', ['traceids']),
    ('coresight-etm4x', ['trcid', 'traceid']),
    ('coresight-dummy', ['traceid', 'trcid']),
    ('coresight-uetm', ['traceid', 'trcid']),
]

qdss_component_func = [
    ('coresight-tpdm',              'parse_tpdm_component'),
    ('coresight-static-tpdm',       'parse_tpdm_component'),
    ('coresight-tpda',              'parse_tpda_component'),
    ('coresight-stm',               'parse_stm_component'),
    ('coresight-uetm',              'parse_uetm_component'),
    ('coresight-qmi',               'parse_qmi_component'),
    ('coresight-trace-noc',         'parse_trace_noc_component'),
    ('coresight-remote-etm',        'parse_remote_etm_component'),
    ('coresight-tmc',               'parse_tmc_component'),
    ('coresight-csr',               'parse_csr_component'),
    ('coresight-dummy',             'parse_dummy_component'),
    ('coresight-tgu',               'parse_tgu_component'),
    ('coresight-cti',               'parse_cti_component'),
    ('coresight-secure-etr',        'parse_secure_etr_component'),
    ('coresight-etm4x',             'parse_etm4_platform_component'),
    # funnel variants: dynamic (old), static, and generic (kp6.0+)
    ('coresight-dynamic-funnel',    'parse_funnel_component'),
    ('coresight-funnel',            'parse_funnel_component'),
    ('coresight-static-funnel',     'parse_funnel_component'),
    # replicator variants: dynamic (old), static, and generic (kp6.0+)
    ('coresight-dynamic-replicator', 'parse_replicator_component'),
    ('coresight-replicator',         'parse_replicator_component'),
    ('coresight-static-replicator',  'parse_replicator_component'),
]
class QDSSDump():

    def __init__(self):
        self.tmc_etr_start = None
        self.tmc_etr1_start= None
        self.etf_start = None
        self.tmc_etf_start = None
        self.etm_regs0 = None
        self.etm_regs1 = None
        self.etm_regs2 = None
        self.etm_regs3 = None
        self.dbgui_start = None
        self.tmc_etf_swao_start = None
        self.tmc_etf_swao_reg_start = None

    # Assumptions: Any address given here has been checked for correct magic
    def print_tmc_etf(self, ram_dump):
        if self.tmc_etf_start is None:
            print_out_str(
                "!!! TMC-ETF address has not been set! I can't continue!")
            return

        print_out_str('Now printing TMC-ETF registers to file')
        tmc_etf_out = ram_dump.open_file('tmc_etf.txt')
        for a, b in tmc_registers.items():
            offset, name = b
            tmc_etf_out.write('{0} ({1}): {2:x}\n'.format(
                a, name, ram_dump.read_u32(self.tmc_etf_start + offset, False)))
        tmc_etf_out.close()

    def print_tmc_etf_swao(self, ram_dump):
        if self.tmc_etf_swao_reg_start is None:
            print_out_str(
                "!!! TMC-ETF-SWAO address has not been set! I can't continue!")
            return

        print_out_str('Now printing TMC-ETF-SWAO registers to file')
        tmc_etf_out = ram_dump.open_file('tmc_etf_swao.txt')
        for a, b in tmc_registers.items():
            offset, name = b
            tmc_etf_out.write('{0} ({1}): {2:x}\n'.format(
                a, name, ram_dump.read_u32(self.tmc_etf_swao_reg_start + offset, False)))
        tmc_etf_out.close()

    def print_tmc_etr(self, ram_dump):
        if self.tmc_etr_start is None:
            print_out_str(
                "!!! TMC-ETR address has not been set! I can't continue!")
            return

        print_out_str('Now printing TMC-ETR registers to file')
        tmc_etf_out = ram_dump.open_file('tmc_etr.txt')
        for a, b in tmc_registers.items():
            offset, name = b
            tmc_etf_out.write('{0} ({1}): {2:x}\n'.format(
                a, name, ram_dump.read_u32(self.tmc_etr_start + offset, False)))
        tmc_etf_out.close()

        if self.tmc_etr1_start is None:
            print_out_str(
                "!!! TMC-ETR1 address has not been set! I can't continue!")
            return

        print_out_str('Now printing TMC-ETR1 registers to file')
        tmc_etf_out = ram_dump.open_file('tmc_etr1.txt')
        for a, b in tmc_registers.items():
            offset, name = b
            tmc_etf_out.write('{0} ({1}): {2:x}\n'.format(
                a, name, ram_dump.read_u32(self.tmc_etr1_start + offset, False)))
        tmc_etf_out.close()

    def print_etm_registers(self, ram_dump, base, fname):
        etm_out = ram_dump.open_file(fname)
        for a, b in etm_registers.items():
            offset, name = b
            etm_out.write('{0} ({1}): {2:x})\n'.format(
                a, name, ram_dump.read_u32(base + offset * 4, False)))
        etm_out.close()

    def print_all_etm_register(self, ram_dump):
        if self.etm_regs0 is None:
            print_out_str(
                '!!! ETM REGS 0 address was not set! Nothing will be parsed')
        else:
            self.print_etm_registers(ram_dump, self.etm_regs0, 'etm_regs0')

        if self.etm_regs1 is None:
            print_out_str(
                '!!! ETM REGS 1 address was not set! Nothing will be parsed')
        else:
            self.print_etm_registers(ram_dump, self.etm_regs1, 'etm_regs1')

        if self.etm_regs2 is None:
            print_out_str(
                '!!! ETM REGS 2 address was not set! Nothing will be parsed')
        else:
            self.print_etm_registers(ram_dump, self.etm_regs2, 'etm_regs2')

        if self.etm_regs3 is None:
            print_out_str(
                '!!! ETM REGS 3 address was not set! Nothing will be parsed')
        else:
            self.print_etm_registers(ram_dump, self.etm_regs3, 'etm_regs3')

    def save_etf_bin(self, ram_dump):
        tmc_etf = ram_dump.open_file('tmc-etf.bin', mode='wb')
        if self.tmc_etf_start is None or self.etf_start is None:
            print_out_str('!!! ETF was not the current sink!')
            tmc_etf.close()
            return

        ctl_offset, ctl_desc = tmc_registers['CTL']
        mode_offset, mode_desc = tmc_registers['MODE']
        rsz_offset, rsz_desc = tmc_registers['RSZ']

        ctl = ram_dump.read_u32(self.tmc_etf_start + ctl_offset, False)
        mode = ram_dump.read_u32(self.tmc_etf_start + mode_offset, False)
        rsz = ram_dump.read_u32(self.tmc_etf_start + rsz_offset, False)
        # rsz is given in words so convert to bytes
        rsz = 4 * rsz

        if (ctl & 0x1) == 1 and (mode == 0):
            for i in range(0, rsz):
                val = ram_dump.read_byte(self.etf_start + i, False)
                tmc_etf.write(struct.pack('<B', val))
        else:
            print_out_str('!!! ETF was not the current sink!')

        tmc_etf.close()

    def save_etf_swao_bin(self, ram_dump):
        tmc_etf_swao = ram_dump.open_file('tmc-etf-swao.bin', mode='wb')
        if self.tmc_etf_swao_reg_start is None or self.tmc_etf_swao_start is None:
            print_out_str('!!! ETF SWAO was not the current sink!')
            tmc_etf_swao.close()
            return

        ctl_offset, ctl_desc = tmc_registers['CTL']
        mode_offset, mode_desc = tmc_registers['MODE']
        rsz_offset, rsz_desc = tmc_registers['RSZ']

        ctl = ram_dump.read_u32(self.tmc_etf_swao_reg_start + ctl_offset, False)
        mode = ram_dump.read_u32(self.tmc_etf_swao_reg_start + mode_offset, False)
        rsz = ram_dump.read_u32(self.tmc_etf_swao_reg_start + rsz_offset, False)
        # rsz is given in words so convert to bytes
        rsz = 4 * rsz

        if (ctl & 0x1) == 1 and (mode == 0):
            for i in range(0, rsz):
                val = ram_dump.read_byte(self.tmc_etf_swao_start + i, False)
                tmc_etf_swao.write(struct.pack('<B', val))
        else:
            print_out_str('!!! ETF SWAO was not the current sink!')

        tmc_etf_swao.close()

    def read_sg_data(self, dbaddr, sts, rwpval, ram_dump, tmc_etr):
        start = dbaddr
        continue_looping = True
        if (sts & 0x1) == 1:
            bottom_delta_read = False
            while continue_looping:
                entry = ram_dump.read_u32(start, False)
                if start == dbaddr and entry is None:
                    return False
                blk = (entry >> 4) << 12
                if (entry & 0x3) == 3:
                    start = blk
                    continue
                elif (entry & 0x2) == 2:
                    if blk <= rwpval and rwpval < (blk + 4096):
                        if not bottom_delta_read:
                            it = range(rwpval, blk + 4096)
                            bottom_delta_read = True
                        else:
                            it = range(blk, blk + (rwpval - blk))
                            continue_looping = False
                    elif bottom_delta_read:
                        it = range(blk, blk + 4096)
                    else:
                        start += 4
                        continue
                    start += 4
                elif (entry & 0x1) == 1:
                    if blk <= rwpval and rwpval < (blk + 4096):
                        if not bottom_delta_read:
                            it = range(rwpval, blk + 4096)
                            bottom_delta_read = True
                        else:
                            it = range(blk, blk + (rwpval - blk))
                            continue_looping = False
                    elif bottom_delta_read:
                        it = range(blk, blk + 4096)
                    else:
                        start = dbaddr
                        continue
                    start = dbaddr
                else:
                    break
                tmc_etr.write(ram_dump.read_physical(it[0], len(it)))
        else:
            while continue_looping:
                entry = ram_dump.read_u32(start, False)
                if start == dbaddr and entry is None:
                    return False
                blk = (entry >> 4) << 12
                if (entry & 0x3) == 3:
                    start = blk
                    continue
                elif (entry & 0x2) == 2:
                    it = range(blk, blk + 4096)
                    start += 4
                elif (entry & 0x1) == 1:
                    it = range(blk, blk + 4096)
                    continue_looping = False
                else:
                    break
                tmc_etr.write(ram_dump.read_physical(it[0], len(it)))
        return True

    def dump_etr_iova(self, start, size, ram_dump, tmc_etr, collapsed_mapping):
        pyh_start = None;
        for virt in sorted(collapsed_mapping.keys()):
            mapping = collapsed_mapping[virt]
            if mapping.mapped and size != 0:
                if start in range(mapping.virt_start, mapping.virt_end):
                    dump_size = min(size, mapping.virt_end - start + 1)
                    pyh_start = mapping.phys_start + (start - mapping.virt_start)
                    it = range(pyh_start, pyh_start + dump_size)
                    size = size - dump_size
                    start = start + dump_size
                    #pyh_start lower 12 bit is PTE flag, so mask the flag.
                    tmc_etr.write(ram_dump.read_physical((it[0] & 0xFFFFFFFFF000), len(it)))
        if pyh_start is None:
            return False
        else:
            return True

    def parse_domain(self, dbaddr, rsz, sts, rwpval, ram_dump, tmc_etr, d, domain_num):
        if d.client_name.endswith(".tmc") or d.client_name.endswith(".etr"):
            flat_mapping = create_flat_mappings(ram_dump, d.pg_table, d.level)
            collapsed_mapping = create_collapsed_mapping(flat_mapping)
            if (sts & 0x1) == 1:
                self.dump_etr_iova(rwpval, dbaddr + rsz - rwpval, ram_dump, tmc_etr, collapsed_mapping)
                return self.dump_etr_iova(dbaddr, rwpval - dbaddr, ram_dump, tmc_etr, collapsed_mapping)
            else:
                return self.dump_etr_iova(dbaddr, rsz, ram_dump, tmc_etr, collapsed_mapping)
        else:
            return False;
        return True;

    def read_data_iova(self, dbaddr, rsz, sts, rwpval, ram_dump, tmc_etr):
        ilib = IommuLib(ram_dump)
        domain_list = ilib.domain_list
        if domain_list is None:
            return False
        for (domain_num, d) in enumerate(domain_list):
            if ((d.domain_type == ARM_SMMU_DOMAIN) or
                    (d.domain_type == MSM_SMMU_AARCH64_DOMAIN)):
                if self.parse_domain(dbaddr, rsz, sts, rwpval, ram_dump, tmc_etr, d, domain_num):
                    print_out_str("Found a correct domain for tmc")
                    return True
        return False

    def find_and_save_etr_domains(self, ram_dump):
        ilib = IommuLib(ram_dump)
        domain_list = ilib.domain_list
        collapsed_mappings = []
        if domain_list is None:
            return None
        for (domain_num, d) in enumerate(domain_list):
            if ((d.domain_type == ARM_SMMU_DOMAIN) or
                    (d.domain_type == MSM_SMMU_AARCH64_DOMAIN)):
                if d.client_name.endswith(".tmc") or d.client_name.endswith(".etr"):
                    flat_mapping = create_flat_mappings(ram_dump, d.pg_table, d.level)
                    collapsed_mapping = create_collapsed_mapping(flat_mapping)
                    collapsed_mappings.append(collapsed_mapping)
        return collapsed_mappings

    def read_iova_pyh_addr(self, iova, collapsed_mappings):
        if collapsed_mappings is None:
            return None
        for collapsed_mapping in collapsed_mappings:
            for virt in sorted(collapsed_mapping.keys()):
                mapping = collapsed_mapping[virt]
                if mapping.mapped:
                    if iova in range(mapping.virt_start, mapping.virt_end):
                        return mapping.phys_start + (iova - mapping.virt_start)
        return None

    def read_sg_data_iova(self, dbaddr, sts, rwpval, ram_dump, tmc_etr):
        collapsed_mappings = self.find_and_save_etr_domains(ram_dump)
        start = self.read_iova_pyh_addr(dbaddr, collapsed_mappings)
        entry = ram_dump.read_u32((start & 0xFFFFFFFFF000), False)
        blk = (entry >> 4) << 12
        read_start = None
        continue_looping = True
        if (sts & 0x1) == 1:
            while continue_looping:
                if (blk >= dbaddr + 4096):
                    read_start = self.read_iova_pyh_addr(blk, collapsed_mappings)
                    it = range(read_start, read_start + 4096)
                    tmc_etr.write(ram_dump.read_physical((it[0] & 0xFFFFFFFFF000), len(it)))
                    blk = blk - 4096
                else:
                    continue_looping = False
        else:
            size = rwpval - dbaddr
            read_size = 4096
            while continue_looping:
                if size > 0:
                    read_start = self.read_iova_pyh_addr(blk, collapsed_mappings)
                    if (size - 4096 < 0):
                        read_size = size
                        size = 0
                    else:
                        blk = blk - 4096
                        size = size - 4096
                    it = range(read_start, read_start + read_size)
                    tmc_etr.write(ram_dump.read_physical((it[0] & 0xFFFFFFFFF000), len(it)))
                else:
                    continue_looping = False
        return True

    def save_etr_bin(self, ram_dump):
        if self.tmc_etr_start is None:
            print_out_str('!!! ETR was not enabled!')
            return
        tmc_etr = ram_dump.open_file('tmc-etr.bin', mode='wb')
        self.do_save_etr_bin(ram_dump, tmc_etr, self.tmc_etr_start)
        tmc_etr.close()

        if self.tmc_etr1_start is None:
            print_out_str('!!! ETR1 was not enabled!')
            return
        tmc_etr1 = ram_dump.open_file('tmc-etr1.bin', mode='wb')
        self.do_save_etr_bin(ram_dump, tmc_etr1, self.tmc_etr1_start)
        tmc_etr1.close()

    def do_save_etr_bin(self, ram_dump, tmc_etr, tmc_etr_start):
        ctl_offset, ctl_desc = tmc_registers['CTL']
        mode_offset, mode_desc = tmc_registers['MODE']

        ctl = ram_dump.read_u32(tmc_etr_start + ctl_offset, False)
        mode = ram_dump.read_u32(tmc_etr_start + mode_offset, False)

        if (ctl & 0x1) == 1 and (mode == 0):
            sts_offset, sts_desc = tmc_registers['STS']
            sts = ram_dump.read_u32(tmc_etr_start + sts_offset, False)

            dbalo_offset, dbalo_desc = tmc_registers['DBALO']
            dbalo = ram_dump.read_u32(
                tmc_etr_start + dbalo_offset, False)
            dbahi_offset, dbahi_desc = tmc_registers['DBAHI']
            dbahi = ram_dump.read_u32(
                tmc_etr_start + dbahi_offset, False)
            dbaddr = (dbahi << 32) + dbalo

            rsz_offset, rsz_desc = tmc_registers['RSZ']
            rsz = ram_dump.read_u32(tmc_etr_start + rsz_offset, False)
            # rsz is given in words so convert to bytes
            rsz = 4 * rsz

            rwp_offset, rwp_desc = tmc_registers['RWP']
            rwp = ram_dump.read_u32(tmc_etr_start + rwp_offset, False)
            rwphi_offset, rwphi_desc = tmc_registers['RWPHI']
            rwphi = ram_dump.read_u32(tmc_etr_start + rwphi_offset, False)
            rwpval = (rwphi << 32) + rwp

            axictl_offset, axictl_desc = tmc_registers["AXICTL"]
            axictl = ram_dump.read_u32(tmc_etr_start + axictl_offset, False)

            if ((axictl >> 7) & 0x1) == 1:
                print_out_str('Scatter gather memory type was selected for TMC ETR')
                if self.read_sg_data(dbaddr, sts, rwpval, ram_dump, tmc_etr) == False:
                    print_out_str('Try virtual address for Scatter gather mode for TMC ETR')
                    self.read_sg_data_iova(dbaddr, sts, rwpval, ram_dump, tmc_etr)
            else:
                if self.read_data_iova(dbaddr, rsz, sts, rwpval, ram_dump, tmc_etr) == False:
                    print_out_str('Contiguous memory type was selected for TMC ETR')
                    if (sts & 0x1) == 1:
                        it1 = range(rwpval, dbaddr+rsz)
                        it2 = range(dbaddr, rwpval)
                        tmc_etr.write(ram_dump.read_physical(it1[0], len(it1)))
                        tmc_etr.write(ram_dump.read_physical(it2[0], len(it2)))
                    else:
                        it = range(dbaddr, dbaddr+rsz)
                        tmc_etr.write(ram_dump.read_physical(it[0], len(it)))
        else:
            print_out_str ('!!! ETR was not the current sink!')

    def print_dbgui_registers(self, ram_dump):
        if self.dbgui_start is None:
            print_out_str(
                "!!!DBGUI address has not been  set! I can't continue!")
            return

        print_out_str('Now printing DBGUI registers to file')
        dbgui_out = ram_dump.open_file('dbgui.txt')
        for a, b in dbgui_registers.items():
            offset, name = b
            dbgui_out.write('{0} ({1}): {2:x}\n'.format(
                a, name, ram_dump.read_u32(self.dbgui_start + offset, False)))

        addr = ram_dump.read_word(ram_dump.address_of('dbgui_drvdata'))
        addr_offset_offset = ram_dump.field_offset('struct dbgui_drvdata', 'addr_offset')
        data_offset_offset = ram_dump.field_offset('struct dbgui_drvdata', 'data_offset')
        size_offset = ram_dump.field_offset('struct dbgui_drvdata', 'size')
        if addr is None or addr_offset_offset is None or data_offset_offset is None or size_offset is None:
            dbgui_out.write('/* struct dbgui_drvdata symbol not available */\n')
            dbgui_out.close()
            return
        addr_offset = ram_dump.read_u32(addr + addr_offset_offset, True)
        data_offset = ram_dump.read_u32(addr + data_offset_offset, True)
        size = ram_dump.read_u32(addr + size_offset, True)

        for i in range(0, size):
            dbgui_out.write('ADDR_{0} ({1:x}) : {2:x}\n'.format(
                i, ram_dump.read_u32(self.dbgui_start + addr_offset + (4 * i), False),
                ram_dump.read_u32(self.dbgui_start + data_offset + (4 * i), False)))
        dbgui_out.close()

    def parse_single_atid(self, driver_name, drvdata, struct_name, atid_fields):
        atid = None
        for field_name in atid_fields:
            try:
                # Try to read the field. If it doesn't exist, this will fail.
                val = self.ramdump.read_structure_field(drvdata, struct_name, field_name)
                if val is not None:
                    atid = val
                    break  # Found a valid field, stop searching
            except Exception:
                continue # Field does not exist, try the next one

        if atid is None:
            return # No suitable ATID field found

        csdev = self.ramdump.read_structure_field(drvdata, struct_name, 'csdev')
        if not csdev:
            return
        dev = self.ramdump.struct_field_addr(csdev, 'struct coresight_device', 'dev')
        csname = self.ramdump.read_cstring(self.ramdump.read_word(dev + self.name_offset))
        print("{:<50} : {:#04x}".format(csname, atid), file=self.f)

    def parse_remote_etm_atid(self, driver_name, drvdata, struct_name, atid_field):
        atid_str = ''
        atid_num = self.ramdump.read_structure_field(drvdata, struct_name, 'num_trcid')
        if atid_num is None:
            return

        atid_addr = None
        for field_name in atid_field:
            try:
                # Try to get the pointer to the trace ids array
                val = self.ramdump.read_structure_field(drvdata, struct_name, field_name)
                if val is not None:
                    atid_addr = val
                    break
            except Exception:
                continue

        if atid_addr is None:
            return

        for i in range(atid_num):
            atid = self.ramdump.read_byte(atid_addr)
            atid_str = "{:#04x}".format(atid) + " " + atid_str
            atid_addr = atid_addr + 1

        remote_etm_csdev = self.ramdump.read_structure_field(drvdata, struct_name, 'csdev')
        if not remote_etm_csdev:
            return
        cs_dev = self.ramdump.struct_field_addr(remote_etm_csdev, 'struct coresight_device', 'dev')
        csname = self.ramdump.read_cstring(self.ramdump.read_word(cs_dev + self.name_offset))
        print("{:<50} : {}".format(csname, atid_str), file=self.f)

    def parse_uetm_atid(self, driver_name, drvdata, struct_name, atid_fields):
        # v2 (kp6.0+): traceid lives in each uetm_instance, not in uetm_drvdata.
        # Iterate uetm_instances[] and print one line per instance.
        members = self.ramdump.get_structure_members(struct_name)
        if members and 'uetm_instances' in members and 'uetm_cnt' in members:
            uetm_cnt = self._read_member(
                drvdata + members['uetm_cnt']['offset'],
                members['uetm_cnt']['size'], False)
            instances_ptr = self.ramdump.read_word(
                drvdata + members['uetm_instances']['offset'])
            if uetm_cnt and instances_ptr:
                # derive instance struct type from field type (e.g. "struct uetm_instance **")
                inst_type = members['uetm_instances'].get('type', 'struct uetm_instance **')
                inst_type = inst_type.strip().rstrip('*').strip()
                inst_m = self.ramdump.get_structure_members(inst_type)
                if inst_m and 'traceid' in inst_m and 'csdev' in inst_m:
                    ptr_size = members['uetm_instances']['size']
                    for i in range(uetm_cnt):
                        inst_ptr = self.ramdump.read_word(instances_ptr + i * ptr_size)
                        if not inst_ptr:
                            continue
                        traceid = self._read_member(
                            inst_ptr + inst_m['traceid']['offset'],
                            inst_m['traceid']['size'], False)
                        csdev = self.ramdump.read_word(
                            inst_ptr + inst_m['csdev']['offset'])
                        if not csdev:
                            continue
                        dev = self.ramdump.struct_field_addr(
                            csdev, 'struct coresight_device', 'dev')
                        csname = self.ramdump.read_cstring(
                            self.ramdump.read_word(dev + self.name_offset))
                        if traceid is not None:
                            print("{:<50} : {:#04x}".format(csname, traceid), file=self.f)
                    return
        # v1 fallback: single traceid field directly in uetm_drvdata.
        # parse_single_atid relies on drvdata->csdev which may not exist in old
        # kernels.  Try it first; if it prints nothing, fall back to naming the
        # entry from the coresight bus device stored in _current_atid_device.
        atid = None
        for field_name in atid_fields:
            try:
                val = self.ramdump.read_structure_field(drvdata, struct_name, field_name)
                if val is not None:
                    atid = val
                    break
            except Exception:
                continue
        if atid is None:
            return

        # Try to get the name from csdev embedded in the struct (normal v1 path).
        csname = None
        csdev = self.ramdump.read_structure_field(drvdata, struct_name, 'csdev')
        if csdev:
            try:
                dev = self.ramdump.struct_field_addr(csdev, 'struct coresight_device', 'dev')
                csname = self.ramdump.read_cstring(
                    self.ramdump.read_word(dev + self.name_offset))
            except Exception:
                pass

        # Fallback for old kernels where csdev is absent: use the coresight bus
        # device name captured in list_qdss_atid.
        if not csname:
            _dev = getattr(self, '_current_atid_device', None)
            if _dev is not None:
                try:
                    csname = self.ramdump.read_cstring(
                        self.ramdump.read_word(
                            _dev + self.kobj_offset + self.name_offset))
                except Exception:
                    pass

        if csname:
            print("{:<50} : {:#04x}".format(csname, atid), file=self.f)

    def _resolve_atid_driver(self, drvname):
        """Normalize driver name variants to the canonical key in qdss_drivers.

        Handles two common naming patterns:
          coresight-stm-platform  -> coresight-stm   (strip -platform suffix)
          coresight-static-tpdm  -> coresight-tpdm   (strip -static- infix)
        """
        if drvname in self.qdss_drivers:
            return drvname
        if drvname.endswith('-platform'):
            base = drvname[:-len('-platform')]
            if base in self.qdss_drivers:
                return base
        normalized = drvname.replace('-static-', '-')
        if normalized in self.qdss_drivers:
            return normalized
        return None

    def list_qdss_atid(self, device):
        drv = self.ramdump.read_structure_field(device, 'struct device', 'driver')
        if not drv:
            return
        drvdata = self.ramdump.read_structure_field(device, 'struct device', 'driver_data')
        if not drvdata:
            return
        drvname = self.ramdump.read_cstring(self.ramdump.read_word(drv + self.dev_drv_offset))

        resolved = self._resolve_atid_driver(drvname)
        if resolved:
            self._current_atid_device = device
            try:
                getattr(QDSSDump, self.qdss_drivers[resolved])(self, resolved, drvdata,
                                self.qdss_structs[resolved], self.atid_fields[resolved])
            except Exception as e:
                print("[Debug] {}: Error parsing ATID for {}: {}".format(
                    drvname, hex(drvdata), e), file=self.f)

    def parse_qdss_component_atid(self, ramdump):
        self.ramdump = ramdump
        self.entry_offset = self.ramdump.field_offset('struct kobject', 'entry')
        self.name_offset = self.ramdump.field_offset('struct kobject', 'name')
        self.dev_drv_offset = self.ramdump.field_offset('struct device_driver', 'name')
        self.kobj_offset = self.ramdump.field_offset('struct device', 'kobj')
        self.qdss_drivers = dict(driver_types)
        self.qdss_structs = dict(driver_structs)
        self.atid_fields = dict(qdss_atid_fields)
        devices_kset = self.ramdump.read_pointer('devices_kset')
        if devices_kset is None:
            print_out_str('!!! devices_kset symbol not found, skipping ATID parse')
            return
        list_head = devices_kset + self.ramdump.field_offset('struct kset', 'list')
        list_offset = self.kobj_offset + self.entry_offset
        list_walker = llist.ListWalker(self.ramdump, list_head, list_offset)
        with open(self.ramdump.outdir + "/ATID.txt", "w") as self.f:
            print("{:<50} {}".format("Source Name", "ATID"), file=self.f)
            print("{}".format("=" * 60), file=self.f)
            list_walker.walk(self.list_qdss_atid)

    def parse_qdss_field(self, addr, stru, field, tab=1, HEX=False, str=False, indent=1):
        try:
            if str:
                val = self.ramdump.read_structure_cstring(addr, stru, field)
            else:
                val = self.ramdump.read_structure_field(addr, stru, field)
                if val is None:
                    raise Exception
                if HEX:
                    val = hex(val)
            print("{}{}{}= {},".format('\t'*indent, field, '\t'*tab, val), file=self.f)
        except Exception:
            print("{}{}{}= Not available,".format('\t'*indent, field, '\t'*tab), file=self.f)

    def parse_clk_core(self, core):
        struct_name = 'struct clk_core'
        print("struct clk_core {} :".format(hex(core)), file=self.f)
        self.parse_dynamic_struct(core, struct_name)

    def parse_clk(self, clk):
        errno_max = -1000
        if clk == 0 or clk > ctypes.c_uint64(errno_max).value:
            return

        struct_name = 'struct clk'
        print("struct clk {} :".format(hex(clk)), file=self.f)
        self.parse_dynamic_struct(clk, struct_name)

        core = self.ramdump.read_structure_field(clk, 'struct clk', 'core')
        if core:
            self.clk_core_set.add(core)

    def _print_csdev_dev_info(self, dev_addr, nesting_level=1):
        """Print key fields of an embedded struct device at dev_addr."""
        indent = '\t' * nesting_level
        dev_m = self.ramdump.get_structure_members('struct device')
        if not dev_m:
            return

        if 'kobj' in dev_m:
            kobj_addr = dev_addr + dev_m['kobj']['offset']
            kobj_m = self.ramdump.get_structure_members('struct kobject')
            if kobj_m and 'name' in kobj_m:
                name_ptr = self.ramdump.read_u64(kobj_addr + kobj_m['name']['offset'])
                if name_ptr:
                    name_str = self.ramdump.read_cstring(name_ptr, 64)
                    print("{}kobj.name\t= \"{}\",".format(indent, name_str or ''), file=self.f)

        if 'driver' in dev_m:
            drv = self.ramdump.read_u64(dev_addr + dev_m['driver']['offset'])
            print("{}driver\t= {},".format(indent, hex(drv) if drv else '0x0'), file=self.f)

        if 'power' in dev_m:
            power_addr = dev_addr + dev_m['power']['offset']
            pm_type = dev_m['power'].get('type', 'struct dev_pm_info').strip()
            pm_m = self.ramdump.get_structure_members(pm_type)
            if pm_m:
                for field in ('runtime_status', 'disable_depth'):
                    if field in pm_m:
                        sz = pm_m[field]['size']
                        val = self._read_member(power_addr + pm_m[field]['offset'], sz, False)
                        if val is not None:
                            print("{}power.{}\t= {},".format(indent, field, val), file=self.f)

    def parse_csdev(self, csdev):
        struct_name = 'struct coresight_device'
        print("coresight_device @ {} :".format(hex(csdev)), file=self.f)
        self.parse_dynamic_struct(csdev, struct_name)

    def parse_tpdm_component(self, drvdata, device):
        struct_name = 'struct tpdm_drvdata'
        print("struct tpdm_drvdata {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name, visited=self._follow_visited)

    def read_array(self, addr, count, datatype):
        array = [0] *count
        if (datatype == 'u8'):
            for i in range(count):
                array[i] = self.ramdump.read_byte(addr)
                addr += 1
        if (datatype == 'u32'):
            for i in range(count):
                array[i] = self.ramdump.read_u32(addr)
                addr += 4
        elif (datatype == 'u64'):
            for i in range(count):
                array[i] = hex(self.ramdump.read_u64(addr))
                addr += 8
        return array

    def parse_tpda_component(self, drvdata, device):
        struct_name = 'struct tpda_drvdata'
        print("struct tpda_drvdata {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name)

    def parse_stm_component(self, drvdata, device):
        struct_name = 'struct stm_drvdata'
        print("struct stm_drvdata {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name)

    def _uetm_instance_type(self):
        """Return the struct type name for uetm_instance, derived from debug info."""
        if not hasattr(self, '_uetm_inst_type_cache'):
            m = self.ramdump.get_structure_members('struct uetm_drvdata')
            if m and 'uetm_instances' in m:
                raw = m['uetm_instances'].get('type', '')
                self._uetm_inst_type_cache = raw.strip().rstrip('*').strip() or 'struct uetm_instance'
            else:
                self._uetm_inst_type_cache = 'struct uetm_instance'
        return self._uetm_inst_type_cache

    def parse_uetm_component(self, drvdata, device):
        # Print uetm_drvdata once (it is shared across all csdevs in v2).
        if not hasattr(self, '_uetm_seen'):
            self._uetm_seen = set()
        if drvdata not in self._uetm_seen:
            self._uetm_seen.add(drvdata)
            struct_name = 'struct uetm_drvdata'
            print("struct uetm_drvdata {} :".format(hex(drvdata)), file=self.f)
            self.parse_dynamic_struct(drvdata, struct_name)
            self._follow_struct_pointers(drvdata, struct_name)

        # v2: each csdev stores its own uetm_instance in csdev->dev.driver_data.
        # v1: csdev->dev.driver_data == drvdata (same pointer) — skip instance block.
        inst_ptr = self.ramdump.read_structure_field(device, 'struct device', 'driver_data')
        if inst_ptr and inst_ptr != drvdata:
            inst_type = self._uetm_instance_type()
            print("{} @ {} :".format(inst_type, hex(inst_ptr)), file=self.f)
            self.parse_dynamic_struct(inst_ptr, inst_type)
            self._follow_struct_pointers(inst_ptr, inst_type)

    def parse_qmi_component(self, drvdata, device):
        struct_name = 'struct qmi_drvdata'
        print("struct qmi_drvdata {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name)

    def parse_trace_noc_component(self, drvdata, device):
        struct_name = 'struct trace_noc_drvdata'
        print("struct trace_noc_drvdata {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name)

    def parse_replicator_component(self, drvdata, device):
        struct_name = 'struct replicator_drvdata'
        print("struct replicator_drvdata {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name)

    def parse_csr_component(self, drvdata, device):
        struct_name = 'struct csr_drvdata'
        print("struct csr_drvdata {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name)

    def _read_member(self, addr, size, is_pointer):
        """Read a scalar/pointer field at addr given its size in bytes."""
        if size == 1:
            val = self.ramdump.read_byte(addr)
        elif size == 2:
            val = self.ramdump.read_u16(addr)
        elif size == 4:
            val = self.ramdump.read_u32(addr)
        elif size == 8:
            val = self.ramdump.read_u64(addr)
        else:
            return None
        if val is not None and is_pointer:
            return hex(val)
        return val

    def _print_struct_members(self, struct_addr, struct_name, nesting_level):
        """Recursively prints all members of struct_name at struct_addr.
        Uses offset/size extracted from ptype /o to avoid separate GDB queries.
        """
        if nesting_level > 8:
            print("{}/* max nesting depth */".format('\t' * nesting_level), file=self.f)
            return
        try:
            members = self.ramdump.get_structure_members(struct_name)
            if not members:
                print("{}/* no symbol info for {} */".format('\t' * nesting_level, struct_name), file=self.f)
                return

            # Pre-scan: collect byte ranges covered by embedded struct/union members.
            # GDB sometimes promotes anonymous-union or named-union members to the
            # parent struct level, producing scalar "ghost" fields whose offsets
            # fall inside an already-present struct/union field.  We suppress them.
            struct_ranges = []
            for minfo in members.values():
                if minfo.get('array_size', 0) > 0 or minfo.get('is_pointer', False):
                    continue
                moff = minfo.get('offset')
                msz  = minfo.get('size')
                if moff is None or msz is None or msz == 0:
                    continue
                if minfo.get('is_struct', False) or msz > 8:
                    struct_ranges.append((moff, moff + msz))

            for member_name, member_info in members.items():
                field_type = member_info.get('type', '')
                array_size = member_info.get('array_size', 0)
                is_pointer = member_info.get('is_pointer', False)
                is_struct = member_info.get('is_struct', False)
                offset = member_info.get('offset')
                size = member_info.get('size')

                if offset is None or size is None:
                    print("{}{}\t= [no layout info],".format('\t' * nesting_level, member_name), file=self.f)
                    continue

                # Suppress ghost scalar/pointer fields promoted from nested
                # unions/structs: skip if their byte range is fully covered by
                # an embedded struct/union field at the same or enclosing offset.
                if array_size == 0 and not (is_struct or (not is_pointer and size > 8)):
                    end = offset + size
                    if any(s <= offset and end <= e for s, e in struct_ranges):
                        continue

                field_addr = struct_addr + offset

                if array_size > 0:
                    # Array: total size / count = element size
                    elem_size = size // array_size if array_size else 0
                    dt = None
                    if elem_size == 1:
                        dt = 'u8'
                    elif elem_size == 4:
                        dt = 'u32'
                    elif elem_size == 8:
                        dt = 'u64'
                    if dt:
                        try:
                            arr = self.read_array(field_addr, array_size, dt)
                            print("{}{}\t= {},".format('\t' * nesting_level, member_name, arr), file=self.f)
                        except Exception:
                            print("{}{}\t= [array read error],".format('\t' * nesting_level, member_name), file=self.f)
                    else:
                        print(
                            "{}{}\t= [array elem size {} unsupported],".format(
                                '\t' * nesting_level, member_name, elem_size),
                            file=self.f)

                elif is_struct or (not is_pointer and size > 8):
                    # Embedded struct or typedef (spinlock_t, atomic_t, …).
                    # Priority: custom handler > blacklist (placeholder) > recursive expand.
                    # The nesting depth cap (level > 8) prevents runaway recursion.
                    handler = self._EMBEDDED_STRUCT_HANDLERS.get((struct_name, member_name))
                    if handler:
                        print("{}{}\t= {{".format('\t' * nesting_level, member_name), file=self.f)
                        getattr(self, handler)(field_addr, nesting_level + 1)
                        print("{}}},".format('\t' * nesting_level), file=self.f)
                    elif field_type in self._POINTER_FOLLOW_BLACKLIST:
                        print("{}{}\t= {{ /* {} ({} bytes) */ }},".format(
                            '\t' * nesting_level, member_name, field_type, size), file=self.f)
                    else:
                        print("{}{}\t= {{".format('\t' * nesting_level, member_name), file=self.f)
                        nested_members = self.ramdump.get_structure_members(field_type)
                        if nested_members:
                            self._print_struct_members(field_addr, field_type, nesting_level + 1)
                        else:
                            print("{}/* {} ({} bytes) */".format(
                                '\t' * (nesting_level + 1), field_type, size), file=self.f)
                        print("{}}},".format('\t' * nesting_level), file=self.f)

                else:
                    # Scalar or pointer: read directly using offset/size from ptype
                    val = self._read_member(field_addr, size, is_pointer)
                    if val is not None:
                        enum_map = self._ENUM_MAPS.get((struct_name, member_name))
                        if enum_map and val in enum_map:
                            display = '{} /* {} */'.format(val, enum_map[val])
                        else:
                            display = val
                        print("{}{}\t= {},".format('\t' * nesting_level, member_name, display), file=self.f)
                    else:
                        print("{}{}\t= Not available,".format('\t' * nesting_level, member_name), file=self.f)
        except Exception as e:
            print("{}/* error parsing {}: {} */".format('\t' * nesting_level, struct_name, str(e)), file=self.f)

    def parse_dynamic_struct(self, struct_addr, struct_name, nesting_level=1):
        """Dynamically discovers and prints all members of a structure."""
        print("{}{{".format('\t' * (nesting_level - 1)), file=self.f)
        self._print_struct_members(struct_addr, struct_name, nesting_level)
        print("{}}}".format('\t' * (nesting_level - 1)), file=self.f)

    def parse_tgu_component(self, drvdata, device):
        struct_name = 'struct tgu_drvdata'
        print("struct tgu_drvdata {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name)

    def parse_cti_component(self, drvdata, device):
        struct_name = 'struct cti_drvdata'
        print("struct cti_drvdata {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name)

    def parse_secure_etr_component(self, drvdata, device):
        struct_name = 'struct secure_etr_drvdata'
        print("struct secure_etr_drvdata {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name)

    def parse_funnel_component(self, drvdata, device):
        struct_name = 'struct funnel_drvdata'
        print("struct funnel_drvdata {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name)

    def parse_dummy_component(self, drvdata, device):
        struct_name = 'struct dummy_drvdata'
        print("struct dummy_drvdata {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name)

    def parse_remote_etm_component(self, drvdata, device):
        import io
        struct_name = 'struct remote_etm_drvdata'
        print("struct remote_etm_drvdata {} :".format(hex(drvdata)), file=self.f)

        # Read traceids array before capturing struct output so we can inline it.
        ids_str = None
        members = self.ramdump.get_structure_members(struct_name)
        if members and 'traceids' in members and 'num_trcid' in members:
            num_trcid = self._read_member(
                drvdata + members['num_trcid']['offset'],
                members['num_trcid']['size'], False)
            traceids_ptr = self.ramdump.read_u64(drvdata + members['traceids']['offset'])
            if traceids_ptr and num_trcid and num_trcid <= 64:
                ids = []
                for i in range(num_trcid):
                    b = self.ramdump.read_byte(traceids_ptr + i)
                    ids.append('0x{:02x}'.format(b) if b is not None else '??')
                ids_str = '[{}]'.format(', '.join(ids))

        # Capture parse_dynamic_struct output and replace the raw pointer line inline.
        real_f = self.f
        self.f = io.StringIO()
        try:
            self.parse_dynamic_struct(drvdata, struct_name)
            struct_out = self.f.getvalue()
        finally:
            self.f = real_f
        if ids_str:
            struct_out = re.sub(
                r'(\btraceids\s*=\s*)0x[0-9a-fA-F]+',
                r'\g<1>' + ids_str,
                struct_out)
        self.f.write(struct_out)

        self._follow_struct_pointers(drvdata, struct_name)

    def parse_tmc_component(self, drvdata, device):
        struct_name = 'struct tmc_drvdata'
        print("tmc_drvdata @ {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name)

    def parse_etm4_platform_component(self, drvdata, device):
        struct_name = 'struct etmv4_drvdata'
        print("struct etmv4_drvdata {} :".format(hex(drvdata)), file=self.f)
        self.parse_dynamic_struct(drvdata, struct_name)
        self._follow_struct_pointers(drvdata, struct_name)

    def _resolve_handler(self, drvname):
        """Return the parse-function name for drvname, or None.

        Lookup order:
          1. Exact match in qdss_components.
          2. Strip a trailing '-platform' suffix (platform-variant naming
             convention: 'coresight-X-platform' -> 'coresight-X').
             This handles any future -platform variant without needing
             an explicit entry in qdss_component_func.
        """
        handler = self.qdss_components.get(drvname)
        if handler is None and drvname.endswith('-platform'):
            handler = self.qdss_components.get(drvname[:-len('-platform')])
        return handler

    def list_qdss_component(self, device):
        bus_type = self.ramdump.read_structure_field(device, 'struct device', 'bus')
        if bus_type != self.coresight_bus:
            return

        # Try to get driver data from the parent device first, then fall back to the current device.
        target_device = self.ramdump.read_structure_field(device, 'struct device', 'parent')
        if not target_device:
            target_device = device # Fallback to self

        drv = self.ramdump.read_structure_field(target_device, 'struct device', 'driver')
        drvdata = self.ramdump.read_structure_field(target_device, 'struct device', 'driver_data')

        # If parent didn't have driver data, fall back to the device itself.
        if not drv or not drvdata:
            target_device = device
            drv = self.ramdump.read_structure_field(target_device, 'struct device', 'driver')
            drvdata = self.ramdump.read_structure_field(target_device, 'struct device', 'driver_data')

        dev_name = self.ramdump.read_cstring(
            self.ramdump.read_word(device + self.kobj_offset + self.name_offset))
        if not drv or not drvdata:
            print(
                "[Debug] {} at {}: Found Coresight device but no driver data.".format(
                    dev_name, hex(device)),
                file=self.f)
            return

        try:
            drvname = self.ramdump.read_cstring(self.ramdump.read_word(drv + self.drvname_offset))
        except Exception:
            print("[Debug] {} at {}: Failed to read driver name.".format(dev_name, hex(device)), file=self.f)
            return

        handler = self._resolve_handler(drvname)
        if handler:
            target_dev_name = self.ramdump.read_cstring(
                self.ramdump.read_word(
                    target_device + self.kobj_offset + self.name_offset))

            print("{}   {}".format(dev_name, hex(device)), file=self.f)
            print("target_dev: {}   {}".format(target_dev_name, hex(target_device)), file=self.f)
            print("driver: {}".format(drvname), file=self.f)
            try:
                getattr(QDSSDump, handler)(self, drvdata, device)
            except Exception as e:
                print("[Debug] {} at {}: Error parsing {} component: {}".format(
                    dev_name, hex(device), drvname, e), file=self.f)
            print("{}".format("=" * 60), file=self.f)
            print("", file=self.f)
        else:
            print(
                "[Debug] {} at {}: Found device with driver '{}', but it is not a "
                "QDSS component.".format(dev_name, hex(device), drvname),
                file=self.f)

    # ── HTML report helpers ──────────────────────────────────────────────────

    # Pointer types with dedicated parse functions.  _follow_struct_pointers
    # calls these instead of the generic auto-follow path, so field renames
    # (e.g. 'csdev' -> 'dev') are handled transparently by type matching.
    _POINTER_SPECIAL_HANDLERS = {
        'struct coresight_device': 'parse_csdev',
        'struct clk':              'parse_clk',
    }

    # Embedded (non-pointer) struct fields too large to auto-expand (>512 bytes).
    # Keyed by (parent_struct_name, field_name) → method name.
    # The method receives (field_addr, nesting_level).
    _EMBEDDED_STRUCT_HANDLERS = {
        ('struct coresight_device', 'dev'): '_print_csdev_dev_info',
    }

    # Kernel infrastructure types: skip entirely (too large, recursive, or
    # carry no useful driver-private state).
    _POINTER_FOLLOW_BLACKLIST = frozenset({
        'struct device', 'struct platform_device', 'struct amba_device',
        'struct miscdevice', 'struct dentry', 'struct task_struct',
        'struct mm_struct', 'struct file', 'struct inode', 'struct kobject',
        'struct module', 'struct bus_type', 'struct device_driver', 'struct class',
        'struct work_struct', 'struct delayed_work', 'struct workqueue_struct',
        'struct timer_list', 'struct completion', 'struct notifier_block',
        'struct regulator', 'struct iommu_domain', 'struct page',
    })

    def _follow_struct_pointers(self, struct_addr, struct_name, visited=None, depth=0):
        """Scan struct_name's pointer-to-struct members and follow each one.

        Per-field dispatch:
          _POINTER_SPECIAL_HANDLERS → call the registered method
          _POINTER_FOLLOW_BLACKLIST → skip silently
          otherwise (driver-private) → auto-follow via parse_dynamic_struct

        Matching is on the POINTEE TYPE, not the field name, so field
        renames between kernel versions are handled transparently.
        """
        if depth > 8:
            return
        if visited is None:
            visited = set()
        if struct_addr in visited:
            return
        visited.add(struct_addr)

        members = self.ramdump.get_structure_members(struct_name)
        if not members:
            return

        for field_name, info in members.items():
            if not info.get('is_pointer') or info.get('array_size', 0) > 0:
                continue

            field_type = info.get('type', '').strip()
            m = re.match(r'^((?:struct|union)\s+\w+)\s*\*$', field_type)
            if not m:
                continue

            pointee_type = m.group(1)
            if pointee_type in self._POINTER_FOLLOW_BLACKLIST:
                continue

            field_addr = struct_addr + info['offset']
            size = info['size']
            if size == 8:
                ptr_val = self.ramdump.read_u64(field_addr)
            elif size == 4:
                ptr_val = self.ramdump.read_u32(field_addr)
            else:
                continue

            if not ptr_val or ptr_val in visited:
                continue

            visited.add(ptr_val)

            special = self._POINTER_SPECIAL_HANDLERS.get(pointee_type)
            if special:
                getattr(self, special)(ptr_val)
                continue

            print("{} @ {} ({}.{}) :".format(
                pointee_type, hex(ptr_val), struct_name, field_name), file=self.f)
            self.parse_dynamic_struct(ptr_val, pointee_type)
            self._follow_struct_pointers(ptr_val, pointee_type, visited, depth + 1)

    _PM_STATUS = {0: ('ACTIVE',    '#f44747'), 1: ('RESUMING',   '#ffd700'),
                  2: ('SUSPENDED', '#6dbf67'), 3: ('SUSPENDING', '#ffd700')}

    _DRIVER_ORDER = [
        'coresight-etm4x', 'coresight-remote-etm',
        'coresight-cti', 'coresight-tmc',
        'coresight-funnel', 'coresight-dynamic-replicator',
        'coresight-tpda', 'coresight-tpdm',
        'coresight-stm', 'coresight-csr',
        'coresight-qmi', 'coresight-tgu', 'coresight-trace-noc',
    ]
    _DRIVER_LABEL = {
        'coresight-etm4x':              'ETM — Embedded Trace Macrocell',
        'coresight-remote-etm':         'Remote ETM',
        'coresight-cti':                'CTI — Cross-Trigger Interface',
        'coresight-tmc':                'TMC — Trace Memory Controller',
        'coresight-funnel':             'Funnel',
        'coresight-dynamic-replicator': 'Dynamic Replicator',
        'coresight-tpda':               'TPDA — Trace Port Data Aggregator',
        'coresight-tpdm':               'TPDM — Trace Port Data Monitor',
        'coresight-stm':                'STM — System Trace Macrocell',
        'coresight-csr':                'CSR — Control & Status Register',
        'coresight-qmi':                'QMI Remote',
        'coresight-tgu':                'TGU — Trigger Generator',
        'coresight-trace-noc':          'Trace NOC',
    }
    _STRUCT_HDR_RE = re.compile(
        r'^(struct\s+\S+\s+(?:@\s+)?0x[0-9a-fA-F]+|\w[\w_]*\s+@\s+0x[0-9a-fA-F]+)'
        r'(\s+\([^)]+\))?\s*:', re.I)

    _ENUM_MAPS = {
        ('struct tmc_drvdata', 'config_type'): {
            0: 'TMC_CONFIG_TYPE_ETB',
            1: 'TMC_CONFIG_TYPE_ETR',
            2: 'TMC_CONFIG_TYPE_ETF',
        },
        ('struct tmc_drvdata', 'etr_mode'): {
            0: 'ETR_MODE_FLAT',
            1: 'ETR_MODE_ETR_SG',
            2: 'ETR_MODE_CATU',
            3: 'ETR_MODE_AUTO',
        },
        ('struct tmc_drvdata', 'out_mode'): {
            0: 'TMC_ETR_OUT_MODE_NONE',
            1: 'TMC_ETR_OUT_MODE_MEM',
            2: 'TMC_ETR_OUT_MODE_USB',
        },
        ('struct etr_buf', 'mode'): {
            0: 'ETR_MODE_FLAT',
            1: 'ETR_MODE_ETR_SG',
            2: 'ETR_MODE_CATU',
            3: 'ETR_MODE_AUTO',
        },
    }

    def _hl_line(self, text):
        t = _html.escape(text)
        t = re.sub(r'(/\*.*?\*/)', r'<span class="cm">\1</span>', t)
        t = re.sub(r'\b(0x[0-9a-fA-F]+)\b',
                   lambda m: '<span class="nl">0x0</span>' if m.group(1) == '0x0'
                             else '<span class="ad">' + m.group(1) + '</span>', t)
        t = re.sub(r'(&quot;[^&]*&quot;)', r'<span class="st">\1</span>', t)
        t = re.sub(r'^(\s+)([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)(\s*=)',
                   r'\1<span class="fn">\2</span>\3', t)
        t = re.sub(r'\b(struct|union)\b', r'<span class="kw">\1</span>', t)
        return t

    def _read_body(self, lines, start):
        """Read lines from `start` (after opening '{') to matching '}'.
        Returns (body_lines, index_after_closing_brace)."""
        body, depth, i = [], 1, start
        while i < len(lines) and depth > 0:
            s = lines[i].strip()
            if s.endswith('{') and '= {' in s and not re.search(r'/\*.*?\*/', s):
                depth += 1
            elif s.startswith('}'):
                depth -= 1
                if depth == 0:
                    return body, i + 1
            body.append(lines[i])
            i += 1
        return body, i

    def _render_fields(self, lines):
        """Render field lines as HTML; nested 'field = {' → collapsible <details>."""
        parts, i = [], 0
        while i < len(lines):
            raw = lines[i]
            s = raw.strip()
            if not s:
                i += 1
                continue
            if s.endswith('{') and '= {' in s and not re.search(r'/\*.*?\*/', s):
                inner, next_i = self._read_body(lines, i + 1)
                close_raw = lines[next_i - 1] if 0 < next_i <= len(lines) else '},'
                parts.append(
                    '<details class="ns">'
                    '<summary class="ns-s">{}</summary>'
                    '<div class="nb">{}</div>'
                    '<div class="fl">{}</div>'
                    '</details>'.format(
                        self._hl_line(raw),
                        self._render_fields(inner),
                        self._hl_line(close_raw)))
                i = next_i
            elif '--- dev (key fields) ---' in s:
                parts.append('<div class="fl devhdr">{}</div>'.format(
                    _html.escape(s.strip())))
                i += 1
            else:
                parts.append('<div class="fl">{}</div>'.format(self._hl_line(raw)))
                i += 1
        return ''.join(parts)

    def _parse_section_blocks(self, lines):
        """Split a device section into (kind, header, body_lines) tuples."""
        blocks, i, meta, first = [], 0, [], True
        while i < len(lines):
            s = lines[i].strip()
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ''
            if self._STRUCT_HDR_RE.match(s) and nxt == '{':
                break
            meta.append(lines[i])
            i += 1
        if meta:
            blocks.append(('meta', '', meta))
        while i < len(lines):
            s = lines[i].strip()
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ''
            if not s:
                i += 1
                continue
            if self._STRUCT_HDR_RE.match(s) and nxt == '{':
                is_csdev = bool(re.match(r'coresight_device @', s, re.I))
                body, next_i = self._read_body(lines, i + 2)
                if is_csdev:
                    j = next_i
                    while j < len(lines):
                        ls = lines[j].strip()
                        if ls.startswith('dev.') or '--- dev (key fields) ---' in ls:
                            body.append(lines[j])
                            j += 1
                        else:
                            break
                    next_i = j
                kind = 'csdev' if is_csdev else ('main' if first else 'struct')
                first = False
                blocks.append((kind, s, body))
                i = next_i
            else:
                i += 1
        return blocks

    def _render_device(self, d, dev_idx):
        display = d['kobj_name'] or d['dev_name']
        bound = d['driver_ptr']
        if bound is None:
            bound_html = ''
        elif bound == '0x0':
            bound_html = '<span class="badge b-ub">&#x2718; unbound</span>'
        else:
            bound_html = '<span class="badge b-bd">&#x2714; bound</span>'
        rs = d['runtime_status']
        plabel, clr = (self._PM_STATUS.get(rs, ('?', '#808080'))
                       if rs is not None else ('?', '#808080'))
        pm_html = ('<span class="badge" style="background:#222;color:{}">'
                   '{}</span>').format(clr, plabel)

        blocks = self._parse_section_blocks(d['raw'].splitlines())
        body_parts = []
        for kind, header, body_lines in blocks:
            if kind == 'meta':
                for ln in body_lines:
                    s = ln.strip()
                    if s.startswith('target_dev:') or s.startswith('driver:'):
                        body_parts.append(
                            '<div class="meta-ln">{}</div>'.format(_html.escape(s)))
            else:
                open_attr = ' open' if kind in ('main', 'csdev') else ''
                body_parts.append(
                    '<details class="sb"{}>'
                    '<summary class="sb-s">{}</summary>'
                    '<div class="sb-b">{}</div>'
                    '</details>'.format(
                        open_attr,
                        _html.escape(header),
                        self._render_fields(body_lines)))
        return (
            '<details class="dev-card" id="dev{}">'
            '<summary class="dev-s">'
            '<b>{}</b>'
            '<span class="b-drv">{}</span>'
            '{}{}'
            '<span class="b-addr">{}</span>'
            '</summary>'
            '<div class="dev-b">{}</div>'
            '</details>'
        ).format(dev_idx,
                 _html.escape(display),
                 _html.escape(d['driver']),
                 bound_html, pm_html,
                 _html.escape(d['dev_addr']),
                 ''.join(body_parts))

    def _parse_section(self, raw):
        """Extract summary metadata from a raw device section string."""
        info = dict(dev_name='', dev_addr='', target_dev='', target_addr='',
                    driver='', kobj_name='', driver_ptr=None,
                    runtime_status=None, mode=None, refcnt=None, raw=raw)
        lines = raw.splitlines()
        if not lines:
            return info

        m = re.match(r'^(\S+)\s+(0x[0-9a-fA-F]+)', lines[0])
        if m:
            info['dev_name'], info['dev_addr'] = m.group(1), m.group(2)

        for line in lines[1:5]:
            m = re.match(r'target_dev:\s+(\S+)\s+(0x[0-9a-fA-F]+)', line)
            if m:
                info['target_dev'], info['target_addr'] = m.group(1), m.group(2)
            m = re.match(r'driver:\s+(\S+)', line)
            if m:
                info['driver'] = m.group(1)

        after_csdev = False
        in_key = False
        for line in lines:
            if re.search(r'coresight_device @', line):
                after_csdev = True
            if '--- dev (key fields) ---' in line:
                in_key = True
                continue
            if in_key:
                m = re.search(r'dev\.kobj\.name\s*=\s*"([^"]*)"', line)
                if m:
                    info['kobj_name'] = m.group(1)
                m = re.search(r'dev\.driver\s*=\s*(0x[0-9a-fA-F]+)', line)
                if m:
                    info['driver_ptr'] = m.group(1)
                m = re.search(r'dev\.power\.runtime_status\s*=\s*(\d+)', line)
                if m:
                    info['runtime_status'] = int(m.group(1))
            if after_csdev and info['mode'] is None:
                m = re.match(r'\s+mode\s*=\s*(\d+),', line)
                if m:
                    info['mode'] = int(m.group(1))
            if after_csdev and info['refcnt'] is None:
                m = re.match(r'\s+refcnt\s*=\s*(\d+),', line)
                if m:
                    info['refcnt'] = int(m.group(1))
        return info

    def _generate_html_report(self):
        txt_path = os.path.join(self.ramdump.outdir, 'coresight.txt')
        html_path = os.path.join(self.ramdump.outdir, 'coresight.html')
        try:
            with open(txt_path, 'r', encoding='utf-8', errors='replace') as fh:
                raw = fh.read()
        except Exception:
            return

        SEP = '=' * 60
        raw_sections = [s.strip() for s in raw.split(SEP + '\n')]
        devices = [self._parse_section(s) for s in raw_sections
                   if s and not s.startswith('[Debug]') and re.match(r'^\S+\s+0x', s)]
        for i, d in enumerate(devices):
            d['idx'] = i

        # Group by driver, preserve preferred order
        groups = {}
        for d in devices:
            groups.setdefault(d['driver'], []).append(d)
        ordered_drivers = ([k for k in self._DRIVER_ORDER if k in groups] +
                           sorted(k for k in groups if k not in self._DRIVER_ORDER))

        # ── Summary table ─────────────────────────────────────────────────────
        tbl_rows = []
        for drv in ordered_drivers:
            label = self._DRIVER_LABEL.get(drv, drv)
            tbl_rows.append(
                '<tr class="grp-hdr"><td colspan="5">{} '
                '<span style="color:#808080;font-size:.85em">({} devices)</span>'
                '</td></tr>'.format(_html.escape(label), len(groups[drv])))
            for d in groups[drv]:
                display = d['kobj_name'] or d['dev_name']
                bound = d['driver_ptr']
                if bound is None:
                    bound_html = '<span style="color:#808080">?</span>'
                elif bound == '0x0':
                    bound_html = '<span style="color:#f44747">&#x2718;</span>'
                else:
                    bound_html = '<span style="color:#6dbf67">&#x2714;</span>'
                rs = d['runtime_status']
                plabel, clr = (self._PM_STATUS.get(rs, ('?', '#808080'))
                               if rs is not None else ('?', '#808080'))
                mode = d['mode']
                mode_html = ('<span style="color:#f44747">{}</span>'.format(mode)
                             if mode else '<span style="color:#6dbf67">0</span>')
                tbl_rows.append(
                    '<tr>'
                    '<td><a href="#dev{}">{}</a></td>'
                    '<td>{}</td>'
                    '<td><span style="color:{}">{}</span></td>'
                    '<td>{}</td>'
                    '<td>{}</td>'
                    '</tr>'.format(
                        d['idx'], _html.escape(display),
                        bound_html, clr, plabel,
                        mode_html,
                        d['refcnt'] if d['refcnt'] is not None else '?'))

        # ── Device detail sections ─────────────────────────────────────────────
        detail_sections = []
        for drv in ordered_drivers:
            label = self._DRIVER_LABEL.get(drv, drv)
            detail_sections.append('<h3>{}</h3>'.format(_html.escape(label)))
            for d in groups[drv]:
                detail_sections.append(self._render_device(d, d['idx']))

        CSS = (
            'body{font-family:monospace;background:#1e1e1e;color:#d4d4d4;margin:2em;line-height:1.5}'
            'h1{color:#fff;border-bottom:2px solid #555;padding-bottom:.3em}'
            'h2{color:#9cdcfe;margin-top:2em;border-left:4px solid #9cdcfe;padding-left:.5em}'
            'h3{color:#ce9178;margin-top:1.5em;margin-bottom:.3em}'
            'table{border-collapse:collapse;width:100%;margin:1em 0}'
            'th{background:#2d2d2d;color:#9cdcfe;text-align:left;padding:6px 10px;border:1px solid #444}'
            'td{padding:5px 10px;border:1px solid #444;vertical-align:top}'
            'tr:nth-child(even){background:#252525}'
            'tr.grp-hdr td{background:#1a2a3a;color:#9cdcfe;font-weight:bold;'
            'padding:4px 10px;border-top:2px solid #9cdcfe}'
            'a{color:#4ec9b0;text-decoration:none} a:hover{text-decoration:underline}'
            '.badge{display:inline-block;padding:1px 7px;border-radius:4px;'
            'font-size:.85em;margin-left:.3em}'
            '.b-ub{background:#3a0000;color:#f44747}'
            '.b-bd{background:#003a00;color:#6dbf67}'
            '.b-drv{background:#2d2d2d;color:#9cdcfe;padding:1px 7px;border-radius:4px;'
            'font-size:.85em;margin-left:.4em}'
            '.b-addr{color:#808080;font-size:.85em;margin-left:.5em}'
            '.dev-card{border:1px solid #444;border-radius:4px;margin:.35em 0}'
            '.dev-card[open]{background:#1a1a1a}'
            '.dev-s{cursor:pointer;padding:.4em .5em;color:#dcdcaa;font-size:1.05em;'
            'list-style:none;display:block}'
            '.dev-s:hover{background:#2a2a2a}'
            '.dev-b{padding:.3em .8em .6em}'
            '.meta-ln{color:#808080;font-size:.9em;padding:.1em 0}'
            '.sb{border:1px solid #333;border-radius:3px;margin:.3em 0}'
            '.sb-s{cursor:pointer;padding:.25em .5em;color:#c586c0;font-weight:bold;'
            'background:#252525;list-style:none;display:block}'
            '.sb-s:hover{background:#2d2d2d}'
            '.sb-b{padding:.3em .6em;background:#1e1e1e}'
            '.ns{border-left:2px solid #2a2a2a;margin-left:2em;margin:.03em 0}'
            '.ns-s{cursor:pointer;padding:.05em .3em;color:#9cdcfe;list-style:none;'
            'display:block;background:transparent}'
            '.ns-s:hover{background:#252525}'
            '.nb{padding-left:1.5em}'
            '.fl{white-space:pre;font-family:monospace;line-height:1.35;padding:0}'
            '.devhdr{color:#dcdcaa;font-weight:bold;margin-top:.4em;'
            'border-top:1px solid #333;padding-top:.3em}'
            '.ad{color:#4ec9b0}.nl{color:#555}.st{color:#ce9178}'
            '.fn{color:#9cdcfe}.kw{color:#c586c0}.cm{color:#6a9955}'
            'hr{border:none;border-top:1px solid #444;margin:2em 0}'
        )
        html = (
            '<!DOCTYPE html><html lang="en"><head>'
            '<meta charset="UTF-8">'
            '<title>CoreSight Device Dump</title>'
            '<style>{}</style></head><body>'
            '<h1>CoreSight Device Dump</h1>'
            '<p style="color:#808080">{} devices</p>'
            '<h2>Device Summary</h2>'
            '<table>'
            '<tr><th>Device</th><th>Bound</th><th>PM Status</th>'
            '<th>Mode</th><th>RefCnt</th></tr>'
            '{}'
            '</table><hr>'
            '<h2>Device Details</h2>'
            '{}'
            '</body></html>'
        ).format(CSS, len(devices), '\n'.join(tbl_rows), '\n'.join(detail_sections))

        with open(html_path, 'w', encoding='utf-8') as fh:
            fh.write(html)

    def parse_qdss_component(self, ramdump):
        self.ramdump = ramdump
        self._follow_visited = set()
        self.qdss_components = dict(qdss_component_func)
        self.entry_offset = self.ramdump.field_offset('struct kobject', 'entry')
        self.name_offset = self.ramdump.field_offset('struct kobject', 'name')
        self.dev_drv_offset = self.ramdump.field_offset('struct device_driver', 'name')
        self.kobj_offset = self.ramdump.field_offset('struct device', 'kobj')
        self.bus_offset = self.ramdump.field_offset('struct device', 'bus')
        self.drvname_offset = self.ramdump.field_offset('struct device_driver', 'name')
        self.amba_dev_offset = self.ramdump.field_offset('struct amba_device', 'dev')
        self.coresight_bus = self.ramdump.address_of('coresight_bustype')
        devices_kset = self.ramdump.read_pointer('devices_kset')
        self.clk_core_set = set()
        self.f = self.ramdump.open_file("coresight.txt")

        if devices_kset is None:
            print_out_str('!!! devices_kset symbol not found, skipping coresight component parse')
            self.f.close()
            return
        list_head = devices_kset + self.ramdump.field_offset('struct kset', 'list')
        list_offset = self.kobj_offset + self.entry_offset
        list_walker = llist.ListWalker(self.ramdump, list_head, list_offset)
        try:
            list_walker.walk(self.list_qdss_component)
            for core in self.clk_core_set:
                self.parse_clk_core(core)
        finally:
            self.f.close()
        self._generate_html_report()

    def dump_standard(self, ram_dump):
        steps = [
            ('print_tmc_etf',             self.print_tmc_etf),
            ('print_tmc_etf_swao',        self.print_tmc_etf_swao),
            ('print_tmc_etr',             self.print_tmc_etr),
            ('print_dbgui_registers',     self.print_dbgui_registers),
            ('print_all_etm_register',    self.print_all_etm_register),
            ('parse_qdss_component_atid', self.parse_qdss_component_atid),
            ('parse_qdss_component',      self.parse_qdss_component),
        ]
        for step_name, step_func in steps:
            try:
                step_func(ram_dump)
            except Exception as e:
                print_out_str('!!! QDSS {}: {}'.format(step_name, e))
