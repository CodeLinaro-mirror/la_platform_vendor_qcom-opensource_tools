# SPDX-License-Identifier: GPL-2.0-only
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.

from parser_util import register_parser, RamParser
from print_out import print_out_str
from ramdump import Struct

QUEUE_HEADER_FIELDS = {
    'status': Struct.get_u32,
    'start_addr': Struct.get_u32,
    'type': Struct.get_u32,
    'queue_size': Struct.get_u32,
    'pkt_size': Struct.get_u32,
    'pkt_drop_cnt': Struct.get_u32,
    'rx_wm': Struct.get_u32,
    'tx_wm': Struct.get_u32,
    'rx_req': Struct.get_u32,
    'tx_req': Struct.get_u32,
    'rx_irq_status': Struct.get_u32,
    'tx_irq_status': Struct.get_u32,
    'read_index': Struct.get_u32,
    'write_index': Struct.get_u32,
}


class HwFenceQueue(Struct):
    _struct_name = 'struct msm_hw_fence_queue'
    _fields = {
        'va_queue': Struct.get_pointer,
        'q_size_bytes': Struct.get_u32,
        'va_header': Struct.get_pointer,
    }


class HwFenceQueuePayload(Struct):
    _struct_name = 'struct msm_hw_fence_queue_payload'
    _fields = {
        'size': Struct.get_u32,
        'type': Struct.get_u16,
        'version': Struct.get_u16,
        'ctxt_id': Struct.get_u64,
        'seqno': Struct.get_u64,
        'hash': Struct.get_u64,
        'flags': Struct.get_u64,
        'client_data': Struct.get_u64,
        'error': Struct.get_u32,
        'timestamp_lo': Struct.get_u32,
        'timestamp_hi': Struct.get_u32,
    }


HW_FENCE_PAYLOAD_TYPE_33 = 0x21


class HwFenceQueuePayloadEnablePower(Struct):
    _struct_name = 'struct msm_hw_fence_queue_payload_enable_power'
    _fields = {
        'size': Struct.get_u32,
        'type': Struct.get_u16,
        'version': Struct.get_u16,
        'response': Struct.get_u32,
        'vm_id': Struct.get_u32,
        'client_id': Struct.get_u32,
        'enable_power': Struct.get_u32,
        'timestamp_lo': Struct.get_u32,
        'timestamp_hi': Struct.get_u32,
    }


class HwFenceEvent(Struct):
    _struct_name = 'struct msm_hw_fence_event'
    _fields = {
        'time': Struct.get_u64,
        'cpu': Struct.get_u32,
        'data_cnt': Struct.get_u32,
    }


class HwFence(Struct):
    _struct_name = 'struct msm_hw_fence'
    _fields = {
        'valid': Struct.get_u32,
        'error': Struct.get_u32,
        'ctx_id': Struct.get_u64,
        'seq_id': Struct.get_u64,
        'wait_client_mask': Struct.get_u64,
        'fence_allocator': Struct.get_u32,
        'fence_signal_client': Struct.get_u32,
        'lock': Struct.get_u64,
        'flags': Struct.get_u64,
        'parents_cnt': Struct.get_u32,
        'pending_child_cnt': Struct.get_u32,
        'fence_create_time': Struct.get_u64,
        'fence_trigger_time': Struct.get_u64,
        'fence_wait_time': Struct.get_u64,
        'refcount': Struct.get_u32,
        'h_synx': Struct.get_u32,
        'client_data': Struct.get_u64,
    }


class HwFenceClient(Struct):
    _struct_name = 'struct msm_hw_fence_client'
    _fields = {
        'client_id': Struct.get_u32,
        'queues_num': Struct.get_u32,
    }


class HwFenceDriverData(Struct):
    _struct_name = 'struct hw_fence_driver_data'
    _fields = {
        'hw_fences_tbl': Struct.get_pointer,
        'hw_fences_tbl_cnt': Struct.get_u32,
        'events': Struct.get_pointer,
        'total_events': Struct.get_u32,
        'client_lock_tbl': Struct.get_pointer,
        'client_lock_tbl_cnt': Struct.get_u32,
        'clients': Struct.get_pointer,
        'clients_num': Struct.get_u32,
        'has_soccp': Struct.get_u8,
    }


@register_parser('--print-hwfenceinfo',
                  'print hw-fence global table, debug events, and ctrl/client queues')
class HwFenceInfo(RamParser):

    def _find_symbol(self, name):
        """address_of() only searches GDB/vmlinux. hw_fence builds as the
        msm_hw_fence.ko module, so fall back to the combined lookup_table
        (which includes module kallsyms) when GDB fails."""
        addr = self.ramdump.address_of(name)
        if addr is not None:
            return addr
        lookup = getattr(self.ramdump, 'lookup_table', None)
        if not lookup:
            return None
        for entry in lookup:
            if entry[1] == name:
                return entry[0]
        return None

    def get_drv_data(self):
        drv_data_addr = self._find_symbol('hw_fence_drv_data')
        if not drv_data_addr:
            print_out_str("hw_fence_drv_data symbol not found. hw_fence builds as "
                           "msm_hw_fence.ko, not into vmlinux -- pass -m "
                           "<dir-with-msm_hw_fence.ko(.unstripped)> so module symbols "
                           "are available.")
            return None

        drv_data_ptr = self.ramdump.read_pointer(drv_data_addr)
        if not drv_data_ptr:
            print_out_str("hw_fence_drv_data pointer is NULL")
            return None

        drv_data_ptr = self.ramdump.pac_ignore(drv_data_ptr)
        return HwFenceDriverData(self.ramdump, drv_data_ptr)

    def read_u64_array(self, struct_obj, field, count):
        addr = struct_obj.get_address(field)
        return [self.ramdump.read_u64(addr + i * 8) for i in range(count)]

    def read_u32_array(self, struct_obj, field, count):
        addr = struct_obj.get_address(field)
        return [self.ramdump.read_u32(addr + i * 4) for i in range(count)]

    def dump_hw_fence_table(self, drv_data):
        tbl_ptr = self.ramdump.pac_ignore(drv_data.hw_fences_tbl)
        cnt = drv_data.hw_fences_tbl_cnt
        if not tbl_ptr or not cnt:
            print_out_str("hw_fence_table: table empty (ptr=%s cnt=%s)" % (tbl_ptr, cnt))
            return

        entry_size = self.ramdump.sizeof('struct msm_hw_fence')
        outfile = self.ramdump.open_file('display_info/hw_fence_table.txt', 'w')
        written = 0
        try:
            for i in range(cnt):
                fence = HwFence(self.ramdump, tbl_ptr + i * entry_size)
                if (fence.valid == 0 and fence.error == 0 and fence.ctx_id == 0 and
                        fence.seq_id == 0 and fence.wait_client_mask == 0 and
                        fence.fence_allocator == 0 and fence.lock == 0 and fence.flags == 0 and
                        fence.parents_cnt == 0 and fence.pending_child_cnt == 0 and
                        fence.fence_create_time == 0 and fence.fence_trigger_time == 0 and
                        fence.refcount == 0 and fence.h_synx == 0):
                    continue

                parent_list = self.read_u64_array(fence, 'parent_list', 3)

                outfile.write(
                    "idx=%-5d ctx=%-8d seq=%-8d valid=%d error=%d wait_client_mask=0x%x "
                    "fence_allocator=%d fence_signal_client=%d lock=0x%x flags=0x%x "
                    "parents_cnt=%d pending_child_cnt=%d refcount=0x%x h_synx=%d "
                    "client_data=0x%x create=%d trig=%d wait=%d parent_list=%s\n" %
                    (i, fence.ctx_id, fence.seq_id, fence.valid, fence.error,
                     fence.wait_client_mask, fence.fence_allocator, fence.fence_signal_client,
                     fence.lock, fence.flags, fence.parents_cnt, fence.pending_child_cnt,
                     fence.refcount, fence.h_synx, fence.client_data,
                     fence.fence_create_time, fence.fence_trigger_time, fence.fence_wait_time,
                     parent_list))
                written += 1
        finally:
            outfile.close()
        print_out_str("hw_fence_table.txt: wrote %d/%d entries" % (written, cnt))

    def dump_hw_fence_events(self, drv_data):
        events_ptr = self.ramdump.pac_ignore(drv_data.events)
        total_events = drv_data.total_events
        if not events_ptr or not total_events:
            print_out_str("hw_fence_events: events buffer empty")
            return

        entry_size = self.ramdump.sizeof('struct msm_hw_fence_event')
        outfile = self.ramdump.open_file('display_info/hw_fence_events.txt', 'w')
        written = 0
        try:
            for i in range(total_events):
                event = HwFenceEvent(self.ramdump, events_ptr + i * entry_size)
                if event.time == 0:
                    continue

                data_cnt = min(event.data_cnt, 12)
                data = self.read_u32_array(event, 'data', data_cnt)
                data_str = ' '.join('0x%x' % v for v in data)
                outfile.write("[%d][t:%d][cpu:%d] data_cnt:%d data:[%s]\n" %
                               (i, event.time, event.cpu, event.data_cnt, data_str))
                written += 1
        finally:
            outfile.close()
        print_out_str("hw_fence_events.txt: wrote %d/%d entries" % (written, total_events))

    def dump_hw_fence_locks(self, drv_data):
        lock_ptr = self.ramdump.pac_ignore(drv_data.client_lock_tbl)
        cnt = drv_data.client_lock_tbl_cnt
        if not lock_ptr or not cnt:
            print_out_str("hw_fence_locks: locks table empty")
            return

        outfile = self.ramdump.open_file('display_info/hw_fence_locks.txt', 'w')
        try:
            for i in range(cnt):
                val = self.ramdump.read_u64(lock_ptr + i * 8)
                outfile.write("[%d] lock=0x%x\n" % (i, val))
        finally:
            outfile.close()
        print_out_str("hw_fence_locks.txt: wrote %d entries" % cnt)

    def dump_queue_header(self, outfile, va_header, has_soccp, label):
        if not va_header:
            return
        va_header = self.ramdump.pac_ignore(va_header)
        struct_name = ('struct msm_hw_fence_hfi_queue_header_v2' if has_soccp else
                        'struct msm_hw_fence_hfi_queue_header')
        hdr = Struct(self.ramdump, va_header, struct_name=struct_name,
                     fields=QUEUE_HEADER_FIELDS)

        outfile.write(
            "-- %s header -- status=%d start_addr=0x%x type=%d queue_size=%d pkt_size=%d "
            "pkt_drop_cnt=%d rx_wm=%d tx_wm=%d rx_req=%d tx_req=%d rx_irq_status=%d "
            "tx_irq_status=%d read_index=%d write_index=%d\n" %
            (label, hdr.status, hdr.start_addr, hdr.type, hdr.queue_size, hdr.pkt_size,
             hdr.pkt_drop_cnt, hdr.rx_wm, hdr.tx_wm, hdr.rx_req, hdr.tx_req,
             hdr.rx_irq_status, hdr.tx_irq_status, hdr.read_index, hdr.write_index))

    def dump_queue_payloads(self, outfile, va_queue, q_size_bytes, label):
        payload_size = self.ramdump.sizeof('struct msm_hw_fence_queue_payload')
        if not va_queue or not q_size_bytes or not payload_size:
            return

        va_queue = self.ramdump.pac_ignore(va_queue)
        num_entries = q_size_bytes // payload_size
        outfile.write("-- %s payloads (entries=%d) --\n" % (label, num_entries))
        for i in range(num_entries):
            entry_addr = va_queue + i * payload_size
            payload_type = HwFenceQueuePayload(self.ramdump, entry_addr).type
            if payload_type == HW_FENCE_PAYLOAD_TYPE_33:
                payload = HwFenceQueuePayloadEnablePower(self.ramdump, entry_addr)
                outfile.write(
                    "[%-4d] type=%-3d ver=%-3d response=%d vm_id=%d client_id=%d "
                    "enable_power=%d ts=0x%x%08x\n" %
                    (i, payload.type, payload.version, payload.response, payload.vm_id,
                     payload.client_id, payload.enable_power,
                     payload.timestamp_hi, payload.timestamp_lo))
            else:
                payload = HwFenceQueuePayload(self.ramdump, entry_addr)
                outfile.write(
                    "[%-4d] type=%-3d ver=%-3d ctxt=%-8d seqno=%-8d hash=%-16d flags=0x%x "
                    "client_data=0x%x error=%d ts=0x%x%08x\n" %
                    (i, payload.type, payload.version, payload.ctxt_id, payload.seqno,
                     payload.hash, payload.flags, payload.client_data, payload.error,
                     payload.timestamp_hi, payload.timestamp_lo))

    def dump_queue_array(self, outfile, base_addr, num_q, has_soccp):
        queue_struct_size = self.ramdump.sizeof('struct msm_hw_fence_queue')
        for i in range(num_q):
            queue = HwFenceQueue(self.ramdump, base_addr + i * queue_struct_size)
            label = 'TxQ' if (i % 2) == 0 else 'RxQ'
            if num_q > 2:
                label += '[%d]' % i
            self.dump_queue_header(outfile, queue.va_header, has_soccp, label)
            self.dump_queue_payloads(outfile, queue.va_queue, queue.q_size_bytes, label)

    def dump_ctrl_queues(self, drv_data):
        base_addr = drv_data.get_address('ctrl_queues')
        outfile = self.ramdump.open_file('display_info/hw_fence_ctrl_queues.txt', 'w')
        try:
            self.dump_queue_array(outfile, base_addr, 2, drv_data.has_soccp)
        finally:
            outfile.close()
        print_out_str("hw_fence_ctrl_queues.txt written")

    def dump_client_queues(self, drv_data):
        clients_ptr = self.ramdump.pac_ignore(drv_data.clients)
        clients_num = drv_data.clients_num
        if not clients_ptr or not clients_num:
            print_out_str("hw_fence_client_queues: no clients registered")
            return

        ptr_size = self.ramdump.sizeof('void *') or 8
        written = 0
        for i in range(clients_num):
            client_ptr = self.ramdump.read_pointer(clients_ptr + i * ptr_size)
            if not client_ptr:
                continue

            client_ptr = self.ramdump.pac_ignore(client_ptr)
            client = HwFenceClient(self.ramdump, client_ptr)
            queues_base_addr = client.get_address('queues')

            outfile = self.ramdump.open_file('display_info/hw_fence_client_%d.txt' % client.client_id, 'w')
            try:
                self.dump_queue_array(outfile, queues_base_addr, client.queues_num,
                                       drv_data.has_soccp)
            finally:
                outfile.close()
            written += 1
        print_out_str("hw_fence_client_<id>.txt written for %d/%d clients" %
                       (written, clients_num))

    def parse(self):
        drv_data = self.get_drv_data()
        if not drv_data:
            return

        for name, fn in (
            ('hw_fence_table', self.dump_hw_fence_table),
            ('hw_fence_events', self.dump_hw_fence_events),
            ('hw_fence_locks', self.dump_hw_fence_locks),
            ('hw_fence_ctrl_queues', self.dump_ctrl_queues),
            ('hw_fence_client_queues', self.dump_client_queues),
        ):
            try:
                fn(drv_data)
            except Exception as e:
                print_out_str("%s dump failed: %s" % (name, e))
