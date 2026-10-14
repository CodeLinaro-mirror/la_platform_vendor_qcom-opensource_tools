# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: GPL-2.0-only

"""Build a clock-aligned DCP HFI and SDE event-log timeline.

Reads DCP HFI core trace events and decoded SDE event logs, symbolizes DCP
program counters from an optional DCP ELF, aligns clocks using
``hfi_enc_kickoff``, and writes one merged display timeline.
"""

import bisect
import os
import re
import statistics

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection
from parser_util import RamParser
from print_out import print_out_str


DCP_EVENTS_FILE = 'display_info/dcp_hfi_core_dump_events.txt'
SDE_EVENTS_FILE = 'display_info/sde_evtlog_parsed.txt'
MERGED_EVENTS_FILE = 'display_info/dcp_hlos_evtlog_merged.txt'

# OEM trace schemas from dcp_pal_tracing.h. The marker-specific field list
# describes the serialized words after the OEM header and marker ID.
OEM_TRACE_POINTS = {
    (0xD510E11, 1): {
        'function': 'host_dsi_dcs_cmd_tx_unlocked',
        'description': 'DCS command DMA kickoff',
        'fields': ('ctrl_idx', 'dcs_cmd_type', 'cmd_size', 'mipi_flags',
                   'ctrl_flags', 'cmd_mode'),
    },
    (0xD510E11, 2): {
        'function': 'host_dsi_ctrl_message_tx',
        'description': 'DSI message DMA kickoff',
        'fields': ('ctrl_idx', 'cmd_type', 'tx_len', 'flags', 'ctrl_flags'),
    },
    (0xD510E11, 3): {
        'function': 'cmd_dma_done_irq_cb',
        'description': 'DSI command DMA done interrupt received',
        'fields': ('ctrl_id', 'instance_idx', 'intr_type'),
    },
    (0xD510E11, 4): {
        'function': '_cmd_dma_done_wait',
        'description': 'DSI command DMA done wait succeeded',
        'fields': ('ctrl_id', 'status'),
        'decoders': {'status': {0: 'DCP_STATUS_SUCCESS'}},
    },
    (0xD510E11, 5): {
        'function': '_cmd_dma_done_wait',
        'description': 'DSI command DMA done wait timed out',
        'fields': ('ctrl_id', 'timeout_ms', 'error'),
        'decoders': {'error': {0x10bad: 'DCP_PAL_ERR(1)'}},
    },
    (0x11D90E11, 1): {
        'function': 'mdp_hwcommit',
        'description': 'MDP hardware flush triggered',
        'fields': ('display_id', 'core_id', 'pending_flush_modules',
                   'pending_commit'),
    },
    (0x11470E11, 1): {
        'function': 'wr_ptr_irq_cb',
        'description': 'INTF WR_PTR (tear) interrupt received',
        'fields': ('display_id', 'core_id', 'instance_idx'),
    },
    (0x11470E11, 2): {
        'function': 'ctl_done_irq_cb',
        'description': 'CTL_DONE interrupt received',
        'fields': ('display_id', 'core_id', 'instance_idx', 'vsync_cnt',
                   'commit_cnt', 'commit_seq_id'),
    },
    (0x11470E11, 3): {
        'function': 'pp_done_irq_cb',
        'description': 'PP_DONE interrupt received',
        'fields': ('display_id', 'core_id', 'instance_idx'),
    },
    (0x11470E11, 4): {
        'function': 'wb_done_irq_cb',
        'description': 'WB_DONE interrupt received',
        'fields': ('display_id', 'core_id', 'instance_idx'),
    },
    (0x11470E11, 5): {
        'function': 'vsync_irq_cb',
        'description': 'VSYNC interrupt received',
        'fields': ('display_id', 'core_id', 'instance_idx', 'vsync_cnt',
                   'commit_cnt', 'commit_seq_id', 'flush'),
    },
    (0x11470E11, 6): {
        'function': 'vsync_irq_cb_cmd_mode',
        'description': 'VSYNC interrupt received',
        'fields': ('display_id', 'core_id', 'instance_idx', 'vsync_cnt',
                   'commit_cnt', 'commit_seq_id', 'flush'),
    },
}
OEM_HEADERS = set(point[0] for point in OEM_TRACE_POINTS)

DCP_LINE_RE = re.compile(
    r'^\[(\d+)\]\[t:(\d+)\]\[evt:(0x[0-9a-fA-F]+)\]\s*'
    r'data\[(\d+)\]:(.*)$')
SDE_PARSED_RE = re.compile(
    r'^\s*([a-zA-Z0-9_.-]+):(\d+).*?==>\s*(\d+):\s*(-?\d+)\s*'
    r'\[(\d+)\]\s*\[([^\]]+)\](.*)$')
SDE_RAW_RE = re.compile(
    r'^\s*([a-zA-Z0-9_.-]+):(\d+)\s*=>\s*\[\d+:(\d+):\s*'
    r'-?\d+\]\s*\[(\d+)\]\s*:\s*\[([^\]]+)\]\s*:(.*)$')


class DcpElfResolver(object):
    """Resolve DCP program counters using ELF function symbols."""

    def __init__(self, elf_path):
        self.symbols = []
        self.symbol_starts = []
        with open(elf_path, 'rb') as elf_file:
            elf = ELFFile(elf_file)
            self._load_symbols(elf)

    def _load_symbols(self, elf):
        # Keep one useful function symbol per address.  Both .symtab and
        # .dynsym are considered because production DCP ELFs may be stripped.
        symbols = {}
        for section in elf.iter_sections():
            if not isinstance(section, SymbolTableSection):
                continue
            for symbol in section.iter_symbols():
                if symbol['st_info']['type'] != 'STT_FUNC' or not symbol.name:
                    continue
                start = int(symbol['st_value'])
                if not start:
                    continue
                size = int(symbol['st_size'])
                previous = symbols.get(start)
                if previous is None or size > previous[1]:
                    symbols[start] = (symbol.name, size)

        ordered = sorted(symbols.items())
        for index, (start, symbol) in enumerate(ordered):
            name, size = symbol
            next_start = ordered[index + 1][0] if index + 1 < len(ordered) \
                else None
            end = start + size if size else next_start
            self.symbols.append((start, end, name))
        self.symbol_starts = [symbol[0] for symbol in self.symbols]

    def _symbol_for(self, address):
        index = bisect.bisect_right(self.symbol_starts, address) - 1
        if index < 0:
            return None
        start, end, name = self.symbols[index]
        if end is not None and address >= end:
            return None
        return name

    def resolve(self, address):
        return self._symbol_for(address)


class DcpHlosEvtlogParser(RamParser):
    """Create a clock-aligned DCP/SDE display event timeline."""

    def _read_lines(self, filename):
        try:
            infile = self.ramdump.open_file(filename, 'r')
        except Exception as err:
            print_out_str('DCP/HLOS merge: cannot read {}: {}'.format(
                filename, err))
            return None
        try:
            return infile.readlines()
        finally:
            infile.close()

    @staticmethod
    def _qtimer_to_ns(ticks):
        # QTimer is 19.2 MHz.  Integer arithmetic avoids float rounding for
        # large 64-bit counter values.
        return (ticks * 10000) // 192

    @staticmethod
    def _parse_hex_values(payload):
        values = []
        for token in payload.split():
            try:
                values.append(int(token.rstrip(','), 16))
            except ValueError:
                continue
        return values

    def _dcp_elf(self):
        value = self.ramdump.dcp_elf
        if value and os.path.isfile(value):
            return value
        if value:
            print_out_str('DCP/HLOS merge: dcp_elf is not a file: {}'.format(
                value))
        return None

    def _load_elf_resolver(self):
        elf = self._dcp_elf()
        try:
            if not elf:
                return None
            resolver = DcpElfResolver(elf)
        except Exception as err:
            print_out_str('DCP/HLOS merge: failed to read DCP ELF: {}'.format(
                err))
            return None
        if not resolver.symbols:
            print_out_str('DCP/HLOS merge: DCP ELF has no function symbols')
        return resolver

    @staticmethod
    def _format_oem_trace(values):
        for index, value in enumerate(values):
            if value not in OEM_HEADERS or index + 1 >= len(values):
                continue
            trace_point = OEM_TRACE_POINTS.get((value, values[index + 1]))
            if trace_point:
                payload = values[index + 2:]
                decoders = trace_point.get('decoders', {})
                fields = []
                for field_index, field_name in enumerate(trace_point['fields']):
                    if field_index >= len(payload):
                        fields.append('{}=<missing>'.format(field_name))
                        continue
                    raw_value = payload[field_index]
                    value_text = '0x{:x}'.format(raw_value)
                    decoded = decoders.get(field_name, {}).get(raw_value)
                    if decoded:
                        value_text += ' ({})'.format(decoded)
                    fields.append('{}={}'.format(field_name, value_text))
                return trace_point['function'], '{}:{}'.format(
                    ' '.join(fields), trace_point['description'])
        return None

    def _parse_dcp(self, lines):
        raw_events = []
        for line in lines:
            match = DCP_LINE_RE.match(line.strip())
            if not match:
                continue
            values = self._parse_hex_values(match.group(5))
            address = values[1] if len(values) > 1 else None
            raw_events.append({
                'index': int(match.group(1)),
                'timestamp': self._qtimer_to_ns(int(match.group(2))),
                'event_address': match.group(3),
                'declared_count': int(match.group(4)),
                'values': values,
                'address': address,
            })

        resolver = self._load_elf_resolver()
        events = []
        for event in raw_events:
            values = event['values']
            trace_id = values[0] if values else 0
            line_number = trace_id & 0xffff
            pid = (trace_id >> 16) & 0xffff
            function = None
            if resolver and event['address'] is not None:
                # DCP return addresses may carry a low-bit tag.
                pc = (event['address'] & ~1) - 1
                function = resolver.resolve(pc)
            oem_trace = self._format_oem_trace(values)
            if oem_trace:
                function, description = oem_trace
            elif function:
                description = ' '.join(
                    '0x{:x}'.format(value) for value in values[2:])
            else:
                function = 'dcp_trace'
                description = 'event={} trace_addr={} {}'.format(
                    event['index'], event['event_address'],
                    ' '.join('0x{:x}'.format(value) for value in values))
            if len(values) != event['declared_count']:
                description += ': Incomplete'
            events.append({
                'timestamp': event['timestamp'],
                'function': function,
                'line': line_number,
                'pid': pid,
                'core': 'DCP',
                'data': description,
            })
        return events

    def _parse_sde(self, lines):
        events = []
        for line in lines:
            match = SDE_PARSED_RE.match(line)
            if match:
                function, line_no, timestamp, _delta, pid, cpu, data = \
                    match.groups()
            else:
                match = SDE_RAW_RE.match(line)
                if not match:
                    continue
                function, line_no, timestamp, pid, cpu, data = match.groups()
            events.append({
                'timestamp': int(timestamp),
                'function': function,
                'line': int(line_no),
                'pid': int(pid),
                'core': 'HLOS',
                'data': 'cpu={} {}'.format(cpu.strip(), data.strip()),
                'raw_data': data.strip(),
            })
        return events

    @staticmethod
    def _kickoff_offset(sde_events):
        offsets = []
        for event in sde_events:
            if event['function'] != 'hfi_enc_kickoff':
                continue
            values = DcpHlosEvtlogParser._parse_hex_values(
                event.get('raw_data', ''))
            if len(values) < 5:
                continue
            arch_timestamp = (values[1] << 32) | values[2]
            local_timestamp = (values[3] << 32) | values[4]
            offsets.append(local_timestamp - arch_timestamp)
        if not offsets:
            return None
        return int(statistics.median(offsets))

    def _write_merged(self, events):
        outfile = self.ramdump.open_file(MERGED_EVENTS_FILE, 'w')
        try:
            outfile.write('-------------------------------------  SDE/DCP INITIAL ANALYSIS  -------------------------------------\n')
            outfile.write('------------------------------------------------------------------------------------------------------\n')
            outfile.write('FUNCTION_NAME:LINE_NO                                 :TIMESTAMP:Delta         [PID]  [Core]DATA\n')
            previous_timestamp = None
            for event in events:
                timestamp = event['timestamp']
                delta = timestamp if previous_timestamp is None \
                    else timestamp - previous_timestamp
                outfile.write('{:<54}:{}:{} {:<7}{:<7}{}\n'.format(
                    '{}:{}'.format(event['function'], event['line']),
                    timestamp, delta, '[{}]'.format(event['pid']),
                    '[{}]'.format(event['core']), event['data']))
                previous_timestamp = timestamp
        finally:
            outfile.close()

    def parse(self):
        dcp_lines = self._read_lines(DCP_EVENTS_FILE)
        sde_lines = self._read_lines(SDE_EVENTS_FILE)
        if dcp_lines is None or sde_lines is None:
            return

        dcp_events = self._parse_dcp(dcp_lines)
        sde_events = self._parse_sde(sde_lines)
        if not dcp_events or not sde_events:
            print_out_str('DCP/HLOS merge: requires valid DCP and SDE events')
            return

        offset = self._kickoff_offset(sde_events)
        if offset is None:
            print_out_str('DCP/HLOS merge: no valid hfi_enc_kickoff clock correlation found')
            return

        for event in dcp_events:
            event['timestamp'] += offset

        # Python's sort is stable, so source order is retained at equal times.
        merged = sorted(dcp_events + sde_events, key=lambda event: event['timestamp'])
        self._write_merged(merged)
        print_out_str('DCP/HLOS merge: wrote {} DCP and {} SDE events to {}'.format(
            len(dcp_events), len(sde_events), MERGED_EVENTS_FILE))
