# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: GPL-2.0-only

"""
SCMI Shared Memory Parser
Reads SCMI channel state from physical memory for ramdump analysis.
"""

import struct

from parser_util import register_parser, RamParser
from print_out import print_out_str

@register_parser('--scmi', 'SCMI Shared Memory Parser with Channel Names and State')
class SCMIParser(RamParser):

    # ------------------------------------------------------------------ #
    #  Channel layout constants
    # ------------------------------------------------------------------ #
    CHANNEL_STRIDE       = 0x1000          # each channel is 4KB apart

    # ------------------------------------------------------------------ #
    #  scmi_shared_mem struct offsets  (documentation-only; reserved fields
    #  are not read but listed here to match the kernel struct layout)
    # ------------------------------------------------------------------ #
    #   0x00  reserved        (u32)
    OFFSET_CHANNEL_STATUS  = 0x04
    #   0x08  reserved1[2]    (u32 × 2 = 8 bytes)
    OFFSET_FLAGS           = 0x10
    OFFSET_LENGTH          = 0x14
    OFFSET_MSG_HEADER      = 0x18
    OFFSET_MSG_PAYLOAD     = 0x1C

    # channel_status bits
    CHANNEL_FREE           = (1 << 0)
    CHANNEL_ERROR          = (1 << 1)

    # flags bits
    INTR_ENABLED           = (1 << 0)

    # msg_header field masks  (ARM DEN0056E §4.2.3)
    MSG_ID_MASK            = 0xFF
    MSG_TYPE_MASK          = 0x3
    MSG_TYPE_SHIFT         = 8
    PROTO_ID_MASK          = 0xFF
    PROTO_ID_SHIFT         = 10

    MAX_PAYLOAD_BYTES      = 128

    # ------------------------------------------------------------------ #
    #  SCMI Protocol IDs → names  (ARM DEN0056E)
    # ------------------------------------------------------------------ #
    PROTOCOL_NAMES = {
        0x10: "Base",
        0x11: "Power Domain",
        0x12: "System Power",
        0x13: "Performance Domain",
        0x14: "Clock",
        0x15: "Sensor",
        0x16: "Reset Domain",
        0x17: "Voltage Domain",
        0x18: "Power Capping",
        0x19: "Pin Control",
    }

    # ------------------------------------------------------------------ #
    #  Message ID → name per protocol  (ARM DEN0056E)
    #
    #  NOTE: PROTOCOL_MSG_NAMES must be defined after all individual dicts
    #  below because it references them by name.
    # ------------------------------------------------------------------ #

    # Common messages (all protocols)
    COMMON_MSG_NAMES = {
        0x00: "PROTOCOL_VERSION",
        0x01: "PROTOCOL_ATTRIBUTES",
        0x02: "PROTOCOL_MESSAGE_ATTRIBUTES",
    }

    # Base Protocol (0x10)
    BASE_MSG_NAMES = {
        **COMMON_MSG_NAMES,
        0x03: "BASE_DISCOVER_VENDOR",
        0x04: "BASE_DISCOVER_SUB_VENDOR",
        0x05: "BASE_DISCOVER_IMPLEMENTATION_VERSION",
        0x06: "BASE_DISCOVER_LIST_PROTOCOLS",
        0x07: "BASE_DISCOVER_AGENT",
        0x08: "BASE_NOTIFY_ERRORS",
        0x09: "BASE_SET_DEVICE_PERMISSIONS",
        0x0A: "BASE_SET_PROTOCOL_PERMISSIONS",
        0x0B: "BASE_RESET_AGENT_CONFIGURATION",
    }

    # Power Domain Protocol (0x11)
    POWER_MSG_NAMES = {
        **COMMON_MSG_NAMES,
        0x03: "POWER_DOMAIN_ATTRIBUTES",
        0x04: "POWER_STATE_SET",
        0x05: "POWER_STATE_GET",
        0x06: "POWER_STATE_NOTIFY",
        0x08: "POWER_DOMAIN_NAME_GET",
    }

    # System Power Protocol (0x12)
    SYSTEM_POWER_MSG_NAMES = {
        **COMMON_MSG_NAMES,
        0x03: "SYSTEM_POWER_STATE_SET",
        0x04: "SYSTEM_POWER_STATE_GET",
        0x05: "SYSTEM_POWER_STATE_NOTIFY",
    }

    # Performance Domain Protocol (0x13)
    PERF_MSG_NAMES = {
        **COMMON_MSG_NAMES,
        0x03: "PERF_DOMAIN_ATTRIBUTES",
        0x04: "PERF_DESCRIBE_LEVELS",
        0x05: "PERF_LIMITS_SET",
        0x06: "PERF_LIMITS_GET",
        0x07: "PERF_LEVEL_SET",
        0x08: "PERF_LEVEL_GET",
        0x09: "PERF_NOTIFY_LIMITS",
        0x0A: "PERF_NOTIFY_LEVEL",
        0x0B: "PERF_DESCRIBE_FASTCHANNEL",
        0x0C: "PERF_DOMAIN_NAME_GET",
    }

    # Clock Protocol (0x14)
    CLOCK_MSG_NAMES = {
        **COMMON_MSG_NAMES,
        0x03: "CLOCK_ATTRIBUTES",
        0x04: "CLOCK_DESCRIBE_RATES",
        0x05: "CLOCK_RATE_SET",
        0x06: "CLOCK_RATE_GET",
        0x07: "CLOCK_CONFIG_SET",
        0x08: "CLOCK_NAME_GET",
        0x09: "CLOCK_RATE_NOTIFY",
        0x0A: "CLOCK_RATE_CHANGE_REQUESTED_NOTIFY",
    }

    # Sensor Protocol (0x15)
    SENSOR_MSG_NAMES = {
        **COMMON_MSG_NAMES,
        0x03: "SENSOR_DESCRIPTION_GET",
        0x04: "SENSOR_TRIP_POINT_NOTIFY",
        0x05: "SENSOR_TRIP_POINT_CONFIG",
        0x06: "SENSOR_READING_GET",
        0x07: "SENSOR_AXIS_DESCRIPTION_GET",
        0x08: "SENSOR_LIST_UPDATE_INTERVALS",
        0x09: "SENSOR_CONFIG_GET",
        0x0A: "SENSOR_CONFIG_SET",
        0x0B: "SENSOR_CONTINUOUS_UPDATE_NOTIFY",
        0x0C: "SENSOR_NAME_GET",
        0x0D: "SENSOR_READING_NOTIFY",
    }

    # Reset Domain Protocol (0x16)
    RESET_MSG_NAMES = {
        **COMMON_MSG_NAMES,
        0x03: "RESET_DOMAIN_ATTRIBUTES",
        0x04: "RESET",
        0x05: "RESET_NOTIFY",
        0x06: "RESET_DOMAIN_NAME_GET",
    }

    # Voltage Domain Protocol (0x17)
    VOLTAGE_MSG_NAMES = {
        **COMMON_MSG_NAMES,
        0x03: "VOLTAGE_DOMAIN_ATTRIBUTES",
        0x04: "VOLTAGE_DESCRIBE_LEVELS",
        0x05: "VOLTAGE_CONFIG_SET",
        0x06: "VOLTAGE_CONFIG_GET",
        0x07: "VOLTAGE_LEVEL_SET",
        0x08: "VOLTAGE_LEVEL_GET",
        0x09: "VOLTAGE_DOMAIN_NAME_GET",
    }

    # Map protocol_id → message name dict
    PROTOCOL_MSG_NAMES = {
        0x10: BASE_MSG_NAMES,
        0x11: POWER_MSG_NAMES,
        0x12: SYSTEM_POWER_MSG_NAMES,
        0x13: PERF_MSG_NAMES,
        0x14: CLOCK_MSG_NAMES,
        0x15: SENSOR_MSG_NAMES,
        0x16: RESET_MSG_NAMES,
        0x17: VOLTAGE_MSG_NAMES,
    }

    # msg_type field values  (ARM DEN0056E §4.2.3)
    MSG_TYPE_NAMES = {
        0: "COMMAND",
        1: "DELAYED_RESPONSE",
        2: "NOTIFICATION",
        3: "RESPONSE",
    }

    # SCMI return status codes  (ARM DEN0056E §4.1.4)
    SCMI_STATUS = {
        0:   "SUCCESS",
        -1:  "NOT_SUPPORTED",
        -2:  "INVALID_PARAMETERS",
        -3:  "DENIED",
        -4:  "NOT_FOUND",
        -5:  "OUT_OF_RANGE",
        -6:  "BUSY",
        -7:  "COMMS_ERROR",
        -8:  "GENERIC_ERROR",
        -9:  "HARDWARE_ERROR",
        -10: "PROTOCOL_ERROR",
    }

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def get_message_name(self, proto_id, msg_id):
        """Return the message name string for (proto_id, msg_id)."""
        msg_map = self.PROTOCOL_MSG_NAMES.get(proto_id, self.COMMON_MSG_NAMES)
        return msg_map.get(msg_id, f"Unknown(0x{msg_id:02X})")

    def get_scmi_base(self):
        """Return the SCMI base address from the board definition.

        Returns None if the board does not define scmi_base — the parser
        will abort rather than guess an address for an unsupported target.
        """
        board = getattr(self.ramdump, 'board', None)
        if board is not None:
            return getattr(board, 'scmi_base', None)
        return None

    def get_scmi_channels(self):
        """Return the channel map from the board definition.

        Returns None if the board does not define scmi_channels.
        """
        board = getattr(self.ramdump, 'board', None)
        if board is not None:
            return getattr(board, 'scmi_channels', None)
        return None

    def read_u32(self, phys_addr):
        """Read a 32-bit little-endian value from a physical address."""
        try:
            val = self.ramdump.read_physical(phys_addr, 4)
            if val is None:
                return None
            return struct.unpack('<I', val)[0]
        except (struct.error, ValueError, TypeError):
            return None
        except Exception as e:
            print_out_str(f"Unexpected error reading 0x{phys_addr:08X}: {e}")
            return None

    def read_phys_bytes(self, phys_addr, length):
        """Read raw bytes from a physical address."""
        try:
            return self.ramdump.read_physical(phys_addr, length)
        except (ValueError, TypeError):
            return None
        except Exception as e:
            print_out_str(f"Unexpected error reading 0x{phys_addr:08X}+{length}: {e}")
            return None

    # ------------------------------------------------------------------ #
    #  Output helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fmt_payload(data):
        """Format payload bytes as 4-byte words separated by two spaces."""
        words = []
        for i in range(0, len(data), 4):
            words.append(' '.join(f'{b:02X}' for b in data[i:i + 4]))
        return '  '.join(words)

    # ------------------------------------------------------------------ #
    #  Payload decoders
    #
    #  Each decoder receives two buffers:
    #    payload      — the full decode buffer (may be larger than reported)
    #    reported_len — the payload byte count from the shared-mem length
    #                   field (length - 4).  Used as the primary discriminator
    #                   between command and response because the platform
    #                   updates the length field when writing the response
    #                   back, even though it does NOT update msg_type.
    # ------------------------------------------------------------------ #

    def _decode_payload(self, proto_id, msg_id, msg_type, payload, reported_len):
        """Dispatch payload decoding to the appropriate protocol handler.

        Returns a list of indented annotation lines (no trailing newline).
        An empty list means no structured decoding is available.
        """
        if proto_id == 0x11:
            return self._decode_power_domain(msg_id, payload, reported_len)
        if proto_id == 0x13:
            return self._decode_perf_domain(msg_id, payload, reported_len)
        if proto_id == 0x16:
            return self._decode_reset_domain(msg_id, payload, reported_len)
        return []

    # Power-state encoding (drivers/firmware/arm_scmi/driver.c)
    #   SCMI_POWER_STATE_PARAM(type, id)
    #     = ((type & BIT(0)) << 30) | (id & 0x0FFFFFFF)
    #   type 0 = ON,  type 1 = OFF
    POWER_STATE_TYPE_SHIFT = 30
    POWER_STATE_ID_MASK    = (1 << 28) - 1   # bits [27:0]

    def _status_str(self, v):
        """Return the SCMI status code name for integer v."""
        return self.SCMI_STATUS.get(v, f"ERROR({v})")

    @staticmethod
    def _power_str(v):
        """Decode a SCMI power_state word into a human-readable string."""
        ptype = (v >> 30) & 0x1
        pid   = v & ((1 << 28) - 1)
        state = "OFF" if ptype else "ON"
        return f"{state} (id={pid})" if pid else state

    def _decode_power_domain(self, msg_id, payload, reported_len):
        """Decode Power Domain POWER_STATE_SET/GET payloads."""
        lines = []

        def u32(off):
            return struct.unpack_from('<I', payload, off)[0] if len(payload) >= off + 4 else None

        def s32(off):
            return struct.unpack_from('<i', payload, off)[0] if len(payload) >= off + 4 else None

        if msg_id == 0x04:  # POWER_STATE_SET
            if reported_len >= 8:          # command: domain_id + power_state
                lines.append("    [cmd] POWER_STATE_SET")
                domain_id   = u32(0)
                power_state = u32(4)
                if domain_id is not None:
                    lines.append(f"    domain_id    : {domain_id}")
                if power_state is not None:
                    lines.append(f"    power_state  : 0x{power_state:08X}  ({self._power_str(power_state)})")
            elif reported_len >= 4:        # response: status only (rx=0)
                lines.append("    [rsp] POWER_STATE_SET")
                st = s32(0)
                if st is not None:
                    lines.append(f"    status       : {st}  ({self._status_str(st)})")
                # Bytes 4-11 hold the original command (domain_id + power_state)
                domain_id   = u32(4)
                power_state = u32(8)
                if domain_id is not None:
                    lines.append(f"    domain_id    : {domain_id}  [from cmd]")
                if power_state is not None:
                    lines.append(f"    power_state  : 0x{power_state:08X}  ({self._power_str(power_state)})  [from cmd]")

        elif msg_id == 0x05:  # POWER_STATE_GET
            if reported_len >= 8:          # response: status + power_state
                lines.append("    [rsp] POWER_STATE_GET")
                st          = s32(0)
                power_state = u32(4)
                if st is not None:
                    lines.append(f"    status       : {st}  ({self._status_str(st)})")
                if power_state is not None:
                    lines.append(f"    power_state  : 0x{power_state:08X}  ({self._power_str(power_state)})")
            elif reported_len >= 4:        # command: domain_id only
                lines.append("    [cmd] POWER_STATE_GET")
                domain_id = u32(0)
                if domain_id is not None:
                    lines.append(f"    domain_id    : {domain_id}")

        return lines

    def _decode_reset_domain(self, msg_id, payload, reported_len):
        """Decode Reset Domain RESET payloads."""
        lines = []

        def u32(off):
            return struct.unpack_from('<I', payload, off)[0] if len(payload) >= off + 4 else None

        def s32(off):
            return struct.unpack_from('<i', payload, off)[0] if len(payload) >= off + 4 else None

        def flags_str(f):
            parts = []
            if f & 0x1: parts.append("AUTONOMOUS")
            if f & 0x2: parts.append("ASSERT")
            if f & 0x4: parts.append("ASYNC")
            return ' | '.join(parts) if parts else "DEASSERT"

        if msg_id == 0x04:  # RESET
            if reported_len >= 12:          # command: domain_id + flags + reset_state
                lines.append("    [cmd] RESET")
                domain_id   = u32(0)
                flags       = u32(4)
                reset_state = u32(8)
                if domain_id is not None:
                    lines.append(f"    domain_id    : {domain_id}")
                if flags is not None:
                    lines.append(f"    flags        : 0x{flags:08X}  ({flags_str(flags)})")
                if reset_state is not None:
                    rs = "ARCH_COLD_RESET" if reset_state == 0 else f"0x{reset_state:08X}"
                    lines.append(f"    reset_state  : {rs}")
            elif reported_len >= 4:         # response: status only (rx=0)
                lines.append("    [rsp] RESET")
                st = s32(0)
                if st is not None:
                    lines.append(f"    status       : {st}  ({self._status_str(st)})")
                # Bytes 4-15 hold the original command data
                domain_id   = u32(4)
                flags       = u32(8)
                reset_state = u32(12)
                if domain_id is not None:
                    lines.append(f"    domain_id    : {domain_id}  [from cmd]")
                if flags is not None:
                    lines.append(f"    flags        : 0x{flags:08X}  ({flags_str(flags)})  [from cmd]")
                if reset_state is not None:
                    rs = "ARCH_COLD_RESET" if reset_state == 0 else f"0x{reset_state:08X}"
                    lines.append(f"    reset_state  : {rs}  [from cmd]")

        return lines

    def _decode_perf_domain(self, msg_id, payload, reported_len):
        """Decode Performance Domain PERF_DESCRIBE_LEVELS/LEVEL_SET/LEVEL_GET payloads."""
        lines = []

        def u32(off):
            return struct.unpack_from('<I', payload, off)[0] if len(payload) >= off + 4 else None

        def u16(off):
            return struct.unpack_from('<H', payload, off)[0] if len(payload) >= off + 2 else None

        def s32(off):
            return struct.unpack_from('<i', payload, off)[0] if len(payload) >= off + 4 else None

        if msg_id == 0x04:  # PERF_DESCRIBE_LEVELS
            # Command: domain(4) + level_index(4) = 8 bytes
            # Response: status(4) + num_returned(u16) + num_remaining(u16) +
            #           N × opp_v3{perf_val(4), power(4), latency_us(2), reserved(2)}
            #           N × opp_v4{...v3..., indicative_freq(4), level_index(4)}
            if reported_len > 8:           # response: has at least one opp entry
                lines.append("    [rsp] PERF_DESCRIBE_LEVELS")
                st = s32(0)
                if st is not None:
                    lines.append(f"    status       : {st}  ({self._status_str(st)})")
                num_ret = u16(4)   # bytes 4-5
                num_rem = u16(6)   # bytes 6-7
                if num_ret is not None:
                    lines.append(f"    returned     : {num_ret}  remaining: {num_rem}")
                    data_bytes = reported_len - 8
                    # Detect v3 (12 bytes/opp) vs v4 (20 bytes/opp).
                    # The kernel uses PROTOCOL_REV_MAJOR(version) to choose,
                    # but the protocol version is not in shared memory.
                    # Use exact size matching:
                    #   v3: data_bytes == num_ret × 12
                    #   v4: data_bytes == num_ret × 20
                    if num_ret > 0 and data_bytes == num_ret * 20:
                        entry_sz, v4 = 20, True
                    elif num_ret > 0 and data_bytes == num_ret * 12:
                        entry_sz, v4 = 12, False
                    else:
                        avg = data_bytes // num_ret if num_ret else 0
                        entry_sz, v4 = (20, True) if avg >= 20 else (12, False)
                    max_opps = data_bytes // entry_sz
                    for i in range(min(num_ret, max_opps)):
                        base = 8 + i * entry_sz
                        pv  = u32(base)
                        pw  = u32(base + 4)
                        lat = u16(base + 8)
                        parts = []
                        if pv  is not None: parts.append(f"perf_val={pv}")
                        if pw  is not None: parts.append(f"power={pw}mW")
                        if lat is not None: parts.append(f"lat={lat}us")
                        if v4:
                            ifreq = u32(base + 12)
                            lidx  = u32(base + 16)
                            if ifreq is not None: parts.append(f"ifreq={ifreq}kHz")
                            if lidx  is not None: parts.append(f"idx={lidx}")
                        lines.append(f"    opp[{i}]      : {', '.join(parts)}")
            elif reported_len >= 8:        # command: domain + level_index
                lines.append("    [cmd] PERF_DESCRIBE_LEVELS")
                domain_id   = u32(0)
                level_index = u32(4)
                if domain_id is not None:
                    lines.append(f"    domain_id    : {domain_id}")
                if level_index is not None:
                    lines.append(f"    level_index  : {level_index}")

        elif msg_id == 0x07:  # PERF_LEVEL_SET
            if reported_len >= 8:          # command: domain + level
                lines.append("    [cmd] PERF_LEVEL_SET")
                domain_id = u32(0)
                perf_lvl  = u32(4)
                if domain_id is not None:
                    lines.append(f"    domain_id    : {domain_id}")
                if perf_lvl is not None:
                    lines.append(f"    perf_level   : {perf_lvl}")
            elif reported_len >= 4:        # response: status only (rx=0)
                lines.append("    [rsp] PERF_LEVEL_SET")
                st = s32(0)
                if st is not None:
                    lines.append(f"    status       : {st}  ({self._status_str(st)})")
                # Bytes 4-7 hold the original level from the command
                pl = u32(4)
                if pl is not None:
                    lines.append(f"    last level   : {pl}  [from cmd]")

        elif msg_id == 0x08:  # PERF_LEVEL_GET
            if reported_len >= 8:          # response: status + level
                lines.append("    [rsp] PERF_LEVEL_GET")
                st       = s32(0)
                perf_lvl = u32(4)
                if st is not None:
                    lines.append(f"    status       : {st}  ({self._status_str(st)})")
                if perf_lvl is not None:
                    lines.append(f"    perf_level   : {perf_lvl}")
            elif reported_len >= 4:        # command: domain only
                lines.append("    [cmd] PERF_LEVEL_GET")
                domain_id = u32(0)
                if domain_id is not None:
                    lines.append(f"    domain_id    : {domain_id}")

        return lines

    # ------------------------------------------------------------------ #
    #  Main entry point
    # ------------------------------------------------------------------ #
    def parse(self):
        base = self.get_scmi_base()
        if base is None:
            print_out_str("SCMIParser: board does not define scmi_base "
                          "-- unsupported target, skipping.")
            return
        channel_names = self.get_scmi_channels()
        if channel_names is None:
            print_out_str("SCMIParser: board does not define scmi_channels "
                          "-- unsupported target, skipping.")
            return
        active_count = 0
        uninit_count = 0
        error_channels = []

        SEP  = "-" * 60
        WIDE = "=" * 60

        with self.ramdump.open_file('scmi.txt') as out:

            out.write(WIDE + "\n")
            out.write("  SCMI Channel Dump\n")
            out.write(f"  Base Address : 0x{base:08X}\n")
            out.write(WIDE + "\n\n")

            for chan_id, chan_name in channel_names.items():
                chan_addr = base + (chan_id * self.CHANNEL_STRIDE)

                status = self.read_u32(chan_addr + self.OFFSET_CHANNEL_STATUS)

                # ── Uninitialized channel (all bits set) ──────────────
                if status == 0xFFFFFFFF:
                    uninit_count += 1
                    out.write(f"--- Ch {chan_id:02d} [{chan_name}]  @ 0x{chan_addr:08X}  [UNINITIALIZED] ---\n\n")
                    continue

                # ── Active channel ────────────────────────────────────
                active_count += 1

                # Build status badge for the header line
                if status is None:
                    badge = "[?]"
                else:
                    free  = "FREE" if (status & self.CHANNEL_FREE) else "BUSY"
                    error = "+ERR" if (status & self.CHANNEL_ERROR) else ""
                    badge = f"[{free}{error}]"
                    if error:
                        error_channels.append(chan_id)

                out.write(f"--- Ch {chan_id:02d} [{chan_name}]  @ 0x{chan_addr:08X}  {badge} ---\n")

                # --- status ---
                if status is None:
                    out.write("  Status   : <unreadable>\n")
                else:
                    free  = "FREE" if (status & self.CHANNEL_FREE) else "BUSY"
                    error = " | ERROR" if (status & self.CHANNEL_ERROR) else ""
                    out.write(f"  Status   : 0x{status:08X}  ({free}{error})\n")

                # --- flags ---
                flags = self.read_u32(chan_addr + self.OFFSET_FLAGS)
                if flags is None:
                    out.write("  Flags    : <unreadable>\n")
                else:
                    intr = "INTR_ENABLED" if (flags & self.INTR_ENABLED) else "INTR_DISABLED"
                    out.write(f"  Flags    : 0x{flags:08X}  ({intr})\n")

                # --- length ---
                length = self.read_u32(chan_addr + self.OFFSET_LENGTH)
                if length is None:
                    out.write("  Length   : <unreadable>\n")
                else:
                    out.write(f"  Length   : 0x{length:08X}  ({length} bytes)\n")

                # --- msg_header ---
                msg_id = msg_type = proto_id = None   # keep in scope for payload decoder
                header = self.read_u32(chan_addr + self.OFFSET_MSG_HEADER)
                if header is None:
                    out.write("  Header   : <unreadable>\n")
                else:
                    msg_id   = (header >> 0)                   & self.MSG_ID_MASK
                    msg_type = (header >> self.MSG_TYPE_SHIFT)  & self.MSG_TYPE_MASK
                    proto_id = (header >> self.PROTO_ID_SHIFT)  & self.PROTO_ID_MASK

                    proto_name = self.PROTOCOL_NAMES.get(proto_id, f"Unknown(0x{proto_id:02X})")
                    msg_name   = self.get_message_name(proto_id, msg_id)
                    type_name  = self.MSG_TYPE_NAMES.get(msg_type, f"Unknown({msg_type})")

                    out.write(f"  Header   : 0x{header:08X}\n")
                    out.write(f"    Protocol : 0x{proto_id:02X}  ({proto_name})\n")
                    out.write(f"    Msg ID   : 0x{msg_id:02X}  ({msg_name})\n")
                    out.write(f"    Msg Type : {msg_type}     ({type_name})\n")

                # --- payload ---
                if length is not None and 4 < length <= (self.MAX_PAYLOAD_BYTES + 4):
                    payload_len = length - 4
                    payload = self.read_phys_bytes(chan_addr + self.OFFSET_MSG_PAYLOAD, payload_len)
                    if payload:
                        out.write(f"  Payload  : {self._fmt_payload(payload)}\n")
                        if proto_id is not None:
                            # Read extra bytes beyond the reported payload to
                            # recover original command data that the platform
                            # left in memory after writing a short response
                            # (rx=0 for SET commands).  reported_len is passed
                            # separately so decoders use it — not len(buf) —
                            # as the command-vs-response discriminator.
                            decode_len = max(payload_len, 16)
                            decode_buf = (
                                self.read_phys_bytes(
                                    chan_addr + self.OFFSET_MSG_PAYLOAD,
                                    decode_len)
                                or payload
                            )
                            for line in self._decode_payload(
                                    proto_id, msg_id, msg_type,
                                    decode_buf, payload_len):
                                out.write(line + "\n")
                    else:
                        out.write("  Payload  : <unreadable>\n")
                elif length is not None and length <= 4:
                    out.write("  Payload  : <none>\n")
                elif length is not None:
                    out.write(f"  Payload  : <skipped, oversized length=0x{length:08X}>\n")

                out.write("\n")

            # ── Summary ───────────────────────────────────────────────
            total = active_count + uninit_count
            out.write(WIDE + "\n")
            out.write("  Summary\n")
            out.write(SEP + "\n")
            out.write(f"  Total channels  : {total}\n")
            out.write(f"  Active          : {active_count}\n")
            out.write(f"  Uninitialized   : {uninit_count}\n")
            if error_channels:
                ids = ', '.join(str(c) for c in error_channels)
                out.write(f"  Channels w/ ERR : {ids}\n")
            out.write(WIDE + "\n")
            out.write("SCMI Parser complete.\n")

        print_out_str("--- Wrote the output to scmi.txt")
