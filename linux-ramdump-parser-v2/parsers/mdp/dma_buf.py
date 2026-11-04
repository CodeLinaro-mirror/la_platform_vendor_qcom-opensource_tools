# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: GPL-2.0-only

"""Decode SDE register-DMA (LUTDMA) command buffers from a ramdump.

The buffers are the same ones dumped by dump_lutdma_buffers.cmm.  Keeping the
decoder here means a separate T32 session and cp_utils/parse_dma_buf.py are no
longer required to inspect the command stream in a ramdump.
"""

import struct

from parser_util import RamParser
from print_out import print_out_str
from parsers.mdp import PacAwareRamDump


class DmaBufParser(RamParser):
    """Dump and decode the register-DMA buffers retained by the SDE driver."""

    FEATURES = (
        'QSEED', 'GAMUT', 'IGC', 'PCC', 'VLUT', 'MEMC_SKIN', 'MEMC_SKY',
        'MEMC_FOLIAGE', 'MEMC_PROT', 'SIX_ZONE', 'HSIC', 'GC', 'SPR_INIT',
        'SPR_UDC', 'SPR_PU_CFG', 'LTM_INIT', 'LTM_ROI', 'LTM_VLUT',
        'RC_MASK_CFG', 'RC_PU_CFG', 'DEMURA_CFG', 'DEMURA_CFG0_PARAM2',
        'DEMURA_PU_CFG', 'AIQE_MDNIE', 'AIQE_SSRC_CONFIG', 'AIQE_SSRC_DATA',
        'AIQE_ABC', 'AIQE_AI_SCALER', 'DESTINATION_SCALER', 'AIQE_COPR',
        'QRTC',
    )
    DSPP_BLOCKS = ('DSPP_NONE', 'DSPP_0', 'DSPP_1', 'DSPP_2', 'DSPP_3')
    LTM_BLOCKS = ('LTM_NONE', 'LTM_0', 'LTM_1', 'LTM_2', 'LTM_3')
    DS_BLOCKS = ('DS_TOP', 'DS_0', 'DS_1', 'DS_2', 'DS_3')
    SSPP_BLOCKS = (
        'SSPP_NONE', 'SSPP_VIG0', 'SSPP_VIG1', 'SSPP_VIG2', 'SSPP_VIG3',
        'SSPP_VIG4', 'SSPP_VIG5', 'SSPP_VIG6', 'SSPP_VIG7', 'SSPP_DMA0',
        'SSPP_DMA1', 'SSPP_DMA2', 'SSPP_DMA3', 'SSPP_DMA4', 'SSPP_DMA5',
        'SSPP_CSC0', 'SSPP_CSC1', 'SSPP_REPRO0', 'SSPP_REPRO1',
        'SSPP_REPRO2', 'SSPP_REPRO3', 'SSPP_REPRO4', 'SSPP_REPRO5',
        'SSPP_REPRO6', 'SSPP_REPRO7', 'SSPP_REPRO8', 'SSPP_REPRO9',
        'SSPP_REPRO10', 'SSPP_REPRO11', 'SSPP_REPRO12', 'SSPP_REPRO13',
        'SSPP_REPRO14', 'SSPP_REPRO15',
    )

    # enum sde_reg_dma_blk in sde_reg_dma.h.  This is intentionally kept in
    # sync with the current display driver rather than the old cp_utils map.
    BLOCKS = {
        0: 'VIG0', 1: 'VIG1', 2: 'VIG2', 3: 'VIG3', 4: 'LM0', 5: 'LM1',
        6: 'LM2', 7: 'LM3', 8: 'DSPP0', 9: 'DSPP1', 10: 'DSPP2',
        11: 'DSPP3', 12: 'DMA0', 13: 'DMA1', 14: 'DMA2', 15: 'DMA3',
        16: 'SSPP_IGC', 17: 'DSPP_IGC', 18: 'LTM0', 19: 'LTM1',
        20: 'DMA4', 21: 'DMA5', 22: 'LTM2', 23: 'LTM3', 24: 'VIG4',
        25: 'VIG5', 26: 'VIG6', 27: 'VIG7', 31: 'MDSS',
    }
    LUT_BLOCKS = {0: 'IGC', 1: 'GAMUT', 3: 'SIXZONE'}
    OP_MASK = 0xf0000000
    OFFSET_MASK = 0x000fffff
    ABSOLUTE_BIT = 1 << 27

    def __init__(self, dump):
        super(DmaBufParser, self).__init__(dump)
        self.ramdump = PacAwareRamDump(dump)

    @staticmethod
    def _fmt_words(words):
        return ' '.join('0x{:08x}'.format(word) for word in words)

    @staticmethod
    def _payload(words, index, count, name, lines):
        """Return a command payload, reporting a truncated payload if needed."""
        if index + 2 + count > len(words):
            lines.append('{}: truncated payload ({} dwords requested, {} remain)'.format(
                name, count, len(words) - index - 2))
            return None
        return words[index + 2:index + 2 + count]

    def _feature_name(self, feature):
        return self.FEATURES[feature] if feature < len(self.FEATURES) else 'FEATURE_{}'.format(feature)

    def decode_words(self, words):
        """Return decoded lines for a u32 register-DMA command stream.

        Malformed/truncated commands stop decoding.  This is preferable to
        interpreting payload data as subsequent opcodes after a corrupt index.
        """
        lines = []
        index = 0
        while index < len(words):
            command = words[index]
            opcode = command & self.OP_MASK
            offset = command & self.OFFSET_MASK
            absolute = bool(command & self.ABSOLUTE_BIT)

            if command == 0:
                end = index
                while end < len(words) and words[end] == 0:
                    end += 1
                lines.append('NoOp                | x{}'.format(end - index))
                index = end
            elif command == 0x180ac114:
                if index + 1 >= len(words):
                    lines.append('DecodeSelect        | truncated')
                    break
                selected = words[index + 1]
                names = [name for bit, name in sorted(self.BLOCKS.items()) if selected & (1 << bit)]
                unknown = selected & ~sum(1 << bit for bit in self.BLOCKS)
                if unknown:
                    names.append('UNKNOWN(0x{:08x})'.format(unknown))
                lines.append('DecodeSelect        | {}'.format(' | '.join(names) or 'none'))
                index += 2
            elif opcode == 0x10000000:
                if index + 1 >= len(words):
                    lines.append('SingleRegWrite      | truncated')
                    break
                lines.append('SingleRegWrite      | ABSOLUTE_ADDR={} OFFSET=0x{:05x} DATA=0x{:08x}'.format(
                    absolute, offset, words[index + 1]))
                index += 2
            elif opcode == 0x20000000:
                if index + 2 >= len(words):
                    lines.append('SingleRegModify     | truncated')
                    break
                lines.append('SingleRegModify     | ABSOLUTE_ADDR={} OFFSET=0x{:05x} MASK=0x{:08x} DATA=0x{:08x}'.format(
                    absolute, offset, words[index + 1], words[index + 2]))
                index += 3
            elif opcode == 0x30000000:
                if index + 1 >= len(words):
                    lines.append('HwIndexRegWrite     | truncated')
                    break
                count = words[index + 1]
                data = self._payload(words, index, count, 'HwIndexRegWrite', lines)
                if data is None:
                    break
                lines.append('HwIndexRegWrite     | ABSOLUTE_ADDR={} OFFSET=0x{:05x} DATA_CNT={} DATA: {}'.format(
                    absolute, offset, count, self._fmt_words(data)))
                index += 2 + count
            elif opcode == 0x40000000:
                if index + 1 >= len(words):
                    lines.append('AutoIncRegWrite     | truncated')
                    break
                count = words[index + 1]
                data = self._payload(words, index, count, 'AutoIncRegWrite', lines)
                if data is None:
                    break
                lines.append('AutoIncRegWrite     | ABSOLUTE_ADDR={} START_OFFSET=0x{:05x} END_OFFSET=0x{:05x} DATA: {}'.format(
                    absolute, offset, offset + count * 4, self._fmt_words(data)))
                index += 2 + count
            elif opcode == 0x50000000:
                if index + 1 >= len(words):
                    lines.append('MultiRegBlockWrite  | truncated')
                    break
                control = words[index + 1]
                count = control & 0x3fff
                data = self._payload(words, index, count, 'MultiRegBlockWrite', lines)
                if data is None:
                    break
                lines.append('MultiRegBlockWrite  | ABSOLUTE_ADDR={} OFFSET=0x{:05x} DECREMENT={} REG_CNT={} DATA: {}'.format(
                    absolute, offset, bool(control & (1 << 31)), (control >> 16) & 0xf,
                    self._fmt_words(data)))
                index += 2 + count
            elif opcode == 0x60000000:
                if index + 1 >= len(words):
                    lines.append('LutBusWrite          | truncated')
                    break
                control = words[index + 1]
                transfer_size = (control >> 16) & 0xff
                transfers = control & 0x3fff
                count = transfer_size * transfers
                data = self._payload(words, index, count, 'LutBusWrite', lines)
                if data is None:
                    break
                lines.append('LutBusWrite          | TABLE={} BLOCK={} LUT_TRANSFERS={} TRANSFER_SIZE={} DATA: {}'.format(
                    (command >> 16) & 1, self.LUT_BLOCKS.get(command & 0xffff, 'INVALID'),
                    transfers, transfer_size, self._fmt_words(data)))
                index += 2 + count
            else:
                lines.append('INVALID DATA at DWORD 0x{:x}: 0x{:08x}'.format(index, command))
                break
        return lines

    def _array_address(self, symbol):
        try:
            return self.ramdump.address_of(symbol)
        except Exception as exc:
            print_out_str(
                'lutdma: failed to resolve symbol {}: {}'.format(symbol, exc))
            return None

    def _buffer_metadata(self, name, slot, slots):
        """Decode current SDE buffer-array indices into report metadata."""
        metadata = {
            'array': '{}[{}]'.format(name, slot),
            'block': 'N/A',
            'rect': 'N/A',
            'feature': 'N/A',
            'dpu': 'N/A',
        }
        per_feature = 5 * 2
        blocks = {
            'dspp_buf': self.DSPP_BLOCKS,
            'ltm_buf': self.LTM_BLOCKS,
            'ds_buf': self.DS_BLOCKS,
        }
        if name in blocks and slots == len(self.FEATURES) * per_feature:
            feature = slot // per_feature
            instance = (slot // 2) % 5
            metadata.update({
                'array': '{}[feature={}, instance={}, dpu={}]'.format(
                    name, feature, instance, slot % 2),
                'block': blocks[name][instance],
                'feature': '{} ({})'.format(feature, self._feature_name(feature)),
                'dpu': 'DPU_{}'.format(slot % 2),
            })
        elif name == 'sspp_buf':
            per_rect = len(self.FEATURES) * len(self.SSPP_BLOCKS) * 2
            if slots == 2 * per_rect:
                rect = slot // per_rect
                remaining = slot % per_rect
                feature = remaining // (len(self.SSPP_BLOCKS) * 2)
                block = (remaining // 2) % len(self.SSPP_BLOCKS)
                dpu = remaining % 2
                metadata.update({
                    'array': '{}[rect={}, feature={}, block={}, dpu={}]'.format(
                        name, rect, feature, block, dpu),
                    'block': self.SSPP_BLOCKS[block],
                    'rect': 'R{}'.format(rect),
                    'feature': '{} ({})'.format(feature, self._feature_name(feature)),
                    'dpu': 'DPU_{}'.format(dpu),
                })
        elif name == 'last_cmd_buf' and slots == 2:
            metadata.update({
                'array': '{}[dpu={}]'.format(name, slot),
                'block': 'LAST_CMD',
                'dpu': 'DPU_{}'.format(slot),
            })
        return metadata

    def _dump_array(self, out, name, symbols):
        """Dump an array, accepting both global and file-static GDB names."""
        symbol = next((candidate for candidate in symbols
                       if self._array_address(candidate)), None)
        address = self._array_address(symbol) if symbol else None
        if not address:
            return 0
        try:
            array_size = self.ramdump.sizeof(symbol)
        except Exception as exc:
            out.write('Skipping {}: cannot determine array size: {}\n'.format(
                name, exc))
            return 0
        pointer_size = self.ramdump.sizeof('void *') or 8
        if not array_size or array_size % pointer_size:
            return 0

        dumped = 0
        slots = array_size // pointer_size
        for slot in range(slots):
            buf_addr = self.ramdump.read_pointer(address + slot * pointer_size)
            if not buf_addr:
                continue
            self._dump_buffer(out, self._buffer_metadata(name, slot, slots), buf_addr)
            dumped += 1
        return dumped

    def _dump_buffer(self, out, metadata, address):
        def field(field_name):
            offset = self.ramdump.field_offset('struct sde_reg_dma_buffer', field_name)
            return None if offset is None else address + offset

        vaddr_field = field('vaddr')
        size_field = field('buffer_size')
        index_field = field('index')
        name = metadata['array']
        if vaddr_field is None or size_field is None or index_field is None:
            out.write('[{} @ 0x{:x}] unavailable: missing sde_reg_dma_buffer fields\n\n'.format(
                name, address))
            return
        vaddr = self.ramdump.read_pointer(vaddr_field)
        size = self.ramdump.read_u32(size_field)
        used = self.ramdump.read_u32(index_field)
        out.write('[{}]\n'.format(name))
        out.write('block: {}\n'.format(metadata['block']))
        out.write('rect: {}\n'.format(metadata['rect']))
        out.write('feature: {}\n'.format(metadata['feature']))
        out.write('dpu: {}\n'.format(metadata['dpu']))
        out.write('buffer: 0x{:x}\n'.format(address))
        out.write('vaddr: {}\n'.format('0x{:x}'.format(vaddr) if vaddr else 'NULL'))
        out.write('used_size: {}\n'.format('0x{:x}'.format(used) if used is not None else 'unavailable'))
        out.write('max_size: {}\n'.format('0x{:x}'.format(size) if size is not None else 'unavailable'))
        out.write('-' * 80 + '\n')
        if not vaddr or not size or used is None:
            out.write('Command data unavailable.\n\n')
            return
        if used == 0:
            out.write('No commands recorded.\n\n')
            return
        # A corrupt size/index must not turn a diagnostic parser into a huge
        # read.  Hardware buffers are bounded by MAX_DWORDS_SZ (16 Ki dwords).
        if used > size or used > 0x10000:
            out.write('Command data skipped: invalid used_size.\n\n')
            return
        try:
            data = self.ramdump.get_bin_data(self.ramdump.pac_ignore(vaddr), used)
        except Exception as exc:
            out.write('Command data read failed: {}\n\n'.format(exc))
            return
        words = list(struct.unpack('<{}I'.format(len(data) // 4), data[:len(data) & ~3]))
        for line in self.decode_words(words):
            out.write(line + '\n')
        out.write('\n')

    def parse(self):
        try:
            out = self.ramdump.open_file('display_info/lutdma_buffers_parsed.txt', 'w')
        except Exception as exc:
            print_out_str('lutdma: cannot open output: {}'.format(exc))
            return
        try:
            out.write('SDE REGISTER-DMA (LUTDMA) BUFFER DUMP\n')
            out.write('Decoded from the buffers used by dump_lutdma_buffers.cmm.\n\n')
            # dspp_buf is externally visible.  The other arrays are static in
            # current drivers, so use a file-qualified GDB name as a fallback.
            # Absence is expected when the matching DWARF unit was stripped.
            arrays = (
                ('dspp_buf', ('dspp_buf',)),
                ('sspp_buf', ('sspp_buf',
                              "'sde_hw_reg_dma_v1_color_proc.c'::sspp_buf")),
                ('ltm_buf', ('ltm_buf',
                             "'sde_hw_reg_dma_v1_color_proc.c'::ltm_buf")),
                ('ds_buf', ('ds_buf',
                            "'sde_hw_reg_dma_v1_color_proc.c'::ds_buf")),
                ('last_cmd_buf', ('last_cmd_buf',
                                  "'sde_hw_reg_dma_v1.c'::last_cmd_buf")),
            )
            count = sum(self._dump_array(out, name, symbols)
                        for name, symbols in arrays)
            if not count:
                out.write('No accessible register-DMA buffers were found.\n')
        except Exception as exc:
            print_out_str('lutdma: dump failed: {}'.format(exc))
            out.write('Parser failure: {}\n'.format(exc))
        finally:
            try:
                out.close()
            except Exception as exc:
                print_out_str(
                    'lutdma: failed to close output: {}'.format(exc))
            else:
                print_out_str(
                    'lutdma: wrote display_info/lutdma_buffers_parsed.txt')
