# Copyright (c) 2020, The Linux Foundation. All rights reserved.
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

from parser_util import register_parser, RamParser
from print_out import print_out_str

class FtraceParser_Event_List(object):
    EVENT_TYPE_MAP = {
        4: ("kernel_stack", "kernel_stack"),   # TRACE_STACK
        5: ("print", "print"),                 # TRACE_PRINT
        6: ("bprint", "bprint"),               # TRACE_BPRINT
        12: ("user_stack", "user_stack"),      # TRACE_USER_STACK
        14: ("bputs", "bputs"),                # TRACE_BPUTS
    }

    def __init__(self, ramdump):
        self.ramdump = ramdump
        self.ftrace_event_type = {}
        self.ftrace_raw_struct_type = {}
        self.event_name_by_type = {}

        # Offsets
        ftrace_event_call_list_offset = self.ramdump.field_offset("struct trace_event_call", "list")
        ftrace_events_head = self.ramdump.address_of("ftrace_events")
        ftrace_events_entry_offset = self.ramdump.field_offset("struct list_head", "next")
        ftrace_event_call_offset = self.ramdump.field_offset("struct trace_event_call", "event")
        tp_offset = self.ramdump.field_offset("struct trace_event_call", "tp")
        ftrace_event_call_name_offset = self.ramdump.field_offset("struct tracepoint", "name")
        ftrace_event_offset = self.ramdump.field_offset("struct trace_event", "type")

        # Walk the linked list
        ftrace_events_entry = self.ramdump.read_pointer(ftrace_events_head + ftrace_events_entry_offset)
        while ftrace_events_entry != ftrace_events_head:
            ftrace_event = ftrace_events_entry - ftrace_event_call_list_offset
            ftrace_event_data = ftrace_event + ftrace_event_call_offset
            tp_data = ftrace_event + tp_offset

            if not ftrace_event_data:
                break

            event_type = self.ramdump.read_u16(ftrace_event_data + ftrace_event_offset)

            # Architecture-specific pointer read
            if self.ramdump.arm64:
                event_name = self.ramdump.read_u64(tp_data)
                event_name_value = self.ramdump.read_u64(event_name + ftrace_event_call_name_offset)
            else:
                event_name = self.ramdump.read_u32(tp_data)
                event_name_value = self.ramdump.read_u32(event_name + ftrace_event_call_name_offset)

            event_name1 = self.ramdump.read_cstring(event_name_value)
            event_name2 = self.ramdump.read_cstring(event_name)

            # Use mapping if known, otherwise default to event_name1
            if event_type in self.EVENT_TYPE_MAP:
                name, raw = self.EVENT_TYPE_MAP[event_type]
            else:
                name = event_name1
                raw = f"trace_event_raw_{event_name1}"

            self.ftrace_event_type[str(event_type)] = name
            self.ftrace_raw_struct_type[str(event_type)] = raw
            self.event_name_by_type[str(event_type)] = name
            # Advance to next entry
            ftrace_events_entry = self.ramdump.read_pointer(ftrace_events_entry + ftrace_events_entry_offset)
