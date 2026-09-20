# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: GPL-2.0-only

# Dumps the HAB (Hypervisor ABstraction layer) driver state from a kernel ramdump.
#
# Starting from the global hab_driver singleton the parser walks:
#
#   hab_driver
#     ndevices, ctx_cnt, b_loopback, hab_init_success
#     devp[0..ndevices-1]  (struct hab_device array)
#       name, id, pchan_cnt
#       pchannels list  (struct physical_channel)
#         name, is_be, dom_id, vmid_local/remote, vcnt, closed
#         sequence_tx / sequence_rx
#         vchannels list  (struct virtual_channel, linked via pnode)
#           id / otherend_id decoded as VCID(seq, dom, mmid)
#           session_id, closed, otherend_closed
#           tx_cnt, rx_cnt          (atomic64_t — total succeeded sends/recvs)
#           rx_pending_cnt          (messages queued but not yet read by client)
#           rx_pending_cnt_peak     (high-water mark of rx_pending_cnt)
#           rx_pending_sz           (total byte size of pending rx messages)
#           rx_inflight             (rx currently in progress / blocking)
#     uctx_list  (struct uhab_context — one per HAB client process, plus one
#                 shared kernel context)
#       owner (PID), kernel, closing, vcnt, export_total, import_total,
#       pending_cnt
#       exp_whse list  (struct export_desc — memory exported by this context)
#         export_id, vcid_local/remote, domid_local/remote, payload_count,
#         readonly
#       imp_whse rbtree  (struct export_desc_super — memory imported into this
#                         context)
#         export_id, vcid_local/remote, domid_local/remote, payload_count,
#         payload_size, readonly, import_state, is_loopback
#
# Output is written to hab.txt in the output directory.

from parser_util import register_parser, RamParser
from linux_list import ListWalker
from rb_tree import RbTree
from collections import namedtuple

MAX_VMID_NAME_SIZE = 30

# VCID bit-field layout (hab.h)
_VCID_ID_MASK    = 0x00000FFF
_VCID_DOMID_MASK = 0x000FF000
_VCID_MMID_MASK  = 0xFFF00000
_VCID_ID_SHIFT    = 0
_VCID_DOMID_SHIFT = 12
_VCID_MMID_SHIFT  = 20


def _decode_vcid(vcid):
    """Return (seq_id, dom_id, mmid) decoded from a packed VCID integer."""
    seq_id = (vcid & _VCID_ID_MASK)    >> _VCID_ID_SHIFT
    dom_id = (vcid & _VCID_DOMID_MASK) >> _VCID_DOMID_SHIFT
    mmid   = (vcid & _VCID_MMID_MASK)  >> _VCID_MMID_SHIFT
    return seq_id, dom_id, mmid


_ImpEntry = namedtuple('_ImpEntry', [
    'exp_super_addr', 'export_id', 'vcid_local', 'vcid_remote',
    'domid_local', 'domid_remote', 'payload_count', 'readonly',
    'import_state', 'payload_size', 'is_loopback',
])

_ExpEntry = namedtuple('_ExpEntry', [
    'exp_addr', 'export_id', 'vcid_local', 'vcid_remote',
    'domid_local', 'domid_remote', 'payload_count', 'readonly',
    'remote_imported',
])


@register_parser('--hab', 'Dump HAB driver physical/virtual channel stats',
                 optional=True)
class HabParser(RamParser):

    def parse(self):
        with self.ramdump.open_file('hab.txt') as out:
            hab_addr = self._find_symbol('hab_driver')
            self._dump_hab_driver(out, hab_addr)
            self._dump_uctx_list(out, hab_addr)

    # ------------------------------------------------------------------ #
    # hab_driver (global singleton)                                        #
    # ------------------------------------------------------------------ #

    def _find_symbol(self, name):
        """address_of() only searches GDB/vmlinux. Fall back to the combined
        lookup_table (which includes module kallsyms) when GDB fails."""
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

    def _dump_hab_driver(self, out, hab_addr):
        if hab_addr is None:
            out.write('hab_driver symbol not found\n'
                      'If hab is a loadable module, pass -m '
                      '<dir-with-hab.ko> so module symbols are available.\n')
            return

        ndevices = self.ramdump.read_structure_field(
            hab_addr, 'struct hab_driver', 'ndevices')
        devp = self.ramdump.read_structure_field(
            hab_addr, 'struct hab_driver', 'devp')
        ctx_cnt = self.ramdump.read_structure_field(
            hab_addr, 'struct hab_driver', 'ctx_cnt')
        b_loopback = self.ramdump.read_structure_field(
            hab_addr, 'struct hab_driver', 'b_loopback')
        hab_init_success = self.ramdump.read_structure_field(
            hab_addr, 'struct hab_driver', 'hab_init_success')

        out.write('hab_driver @ 0x{:x}\n'.format(hab_addr))
        out.write('  ndevices:         {}\n'.format(ndevices))
        out.write('  ctx_cnt:          {}\n'.format(ctx_cnt))
        out.write('  b_loopback:       {}\n'.format(b_loopback))
        out.write('  hab_init_success: {}\n'.format(hab_init_success))
        out.write('  devp:             0x{:x}\n\n'.format(devp or 0))

        if not devp or not ndevices:
            out.write('No hab_device entries\n')
            return

        for i in range(ndevices):
            dev_addr = self.ramdump.array_index(devp, 'struct hab_device', i)
            self._dump_hab_device(out, dev_addr, i)

    # ------------------------------------------------------------------ #
    # hab_device                                                           #
    # ------------------------------------------------------------------ #

    def _dump_hab_device(self, out, dev_addr, index):
        name_offset = self.ramdump.field_offset('struct hab_device', 'name')
        name = self.ramdump.read_cstring(dev_addr + name_offset,
                                         MAX_VMID_NAME_SIZE)
        dev_id = self.ramdump.read_structure_field(
            dev_addr, 'struct hab_device', 'id')
        pchan_cnt = self.ramdump.read_structure_field(
            dev_addr, 'struct hab_device', 'pchan_cnt')

        out.write('hab_device[{:2d}] @ 0x{:x}  name="{}"  id=0x{:x}'
                  '  pchan_cnt={}\n'.format(
                      index, dev_addr, name or '', dev_id or 0,
                      pchan_cnt or 0))

        # hab_device.pchannels -> physical_channel.node
        pchannels_offset = self.ramdump.field_offset(
            'struct hab_device', 'pchannels')
        node_offset = self.ramdump.field_offset(
            'struct physical_channel', 'node')

        pchan_num = 0
        for pchan_addr in ListWalker(self.ramdump,
                                     dev_addr + pchannels_offset,
                                     node_offset):
            self._dump_physical_channel(out, pchan_addr, pchan_num)
            pchan_num += 1

        if pchan_num == 0:
            out.write('  (no pchannels)\n')
        out.write('\n')

    # ------------------------------------------------------------------ #
    # physical_channel                                                     #
    # ------------------------------------------------------------------ #

    def _dump_physical_channel(self, out, pchan_addr, index):
        name_offset = self.ramdump.field_offset(
            'struct physical_channel', 'name')
        name = self.ramdump.read_cstring(pchan_addr + name_offset,
                                         MAX_VMID_NAME_SIZE)
        is_be = self.ramdump.read_structure_field(
            pchan_addr, 'struct physical_channel', 'is_be')
        dom_id = self.ramdump.read_structure_field(
            pchan_addr, 'struct physical_channel', 'dom_id')
        vmid_local = self.ramdump.read_structure_field(
            pchan_addr, 'struct physical_channel', 'vmid_local')
        vmid_remote = self.ramdump.read_structure_field(
            pchan_addr, 'struct physical_channel', 'vmid_remote')
        vcnt = self.ramdump.read_structure_field(
            pchan_addr, 'struct physical_channel', 'vcnt')
        closed = self.ramdump.read_structure_field(
            pchan_addr, 'struct physical_channel', 'closed')
        seq_tx = self.ramdump.read_structure_field(
            pchan_addr, 'struct physical_channel', 'sequence_tx')
        seq_rx = self.ramdump.read_structure_field(
            pchan_addr, 'struct physical_channel', 'sequence_rx')

        out.write('  pchan[{}] @ 0x{:x}  name="{}"  is_be={}  '
                  'dom_id={}  vmid_local={}  vmid_remote={}  '
                  'vcnt={}  closed={}\n'.format(
                      index, pchan_addr, name or '', is_be or 0,
                      dom_id or 0, vmid_local or 0, vmid_remote or 0,
                      vcnt or 0, closed or 0))
        out.write('           sequence_tx={}  sequence_rx={}\n'.format(
            seq_tx or 0, seq_rx or 0))

        # physical_channel.vchannels -> virtual_channel.pnode
        # NOTE: use pnode (pchan linkage), NOT node (ctx linkage)
        vchannels_offset = self.ramdump.field_offset(
            'struct physical_channel', 'vchannels')
        pnode_offset = self.ramdump.field_offset(
            'struct virtual_channel', 'pnode')

        vchan_num = 0
        for vchan_addr in ListWalker(self.ramdump,
                                     pchan_addr + vchannels_offset,
                                     pnode_offset):
            self._dump_virtual_channel(out, vchan_addr, vchan_num)
            vchan_num += 1

        if vchan_num == 0:
            out.write('           (no vchannels)\n')

    # ------------------------------------------------------------------ #
    # virtual_channel                                                      #
    # ------------------------------------------------------------------ #

    def _dump_virtual_channel(self, out, vchan_addr, index):
        vchan_id = self.ramdump.read_structure_field(
            vchan_addr, 'struct virtual_channel', 'id')
        otherend_id = self.ramdump.read_structure_field(
            vchan_addr, 'struct virtual_channel', 'otherend_id')
        otherend_closed = self.ramdump.read_structure_field(
            vchan_addr, 'struct virtual_channel', 'otherend_closed')
        session_id = self.ramdump.read_structure_field(
            vchan_addr, 'struct virtual_channel', 'session_id')
        closed = self.ramdump.read_structure_field(
            vchan_addr, 'struct virtual_channel', 'closed')

        # atomic64_t is struct { s64 counter; } — counter is at offset 0
        # read_s64 at the atomic's address gives the counter value directly
        tx_cnt_off = self.ramdump.field_offset(
            'struct virtual_channel', 'tx_cnt')
        rx_cnt_off = self.ramdump.field_offset(
            'struct virtual_channel', 'rx_cnt')
        tx_cnt = (self.ramdump.read_s64(vchan_addr + tx_cnt_off)
                  if tx_cnt_off is not None else None)
        rx_cnt = (self.ramdump.read_s64(vchan_addr + rx_cnt_off)
                  if rx_cnt_off is not None else None)

        rx_pending_cnt = self.ramdump.read_structure_field(
            vchan_addr, 'struct virtual_channel', 'rx_pending_cnt')
        rx_pending_cnt_peak = self.ramdump.read_structure_field(
            vchan_addr, 'struct virtual_channel', 'rx_pending_cnt_peak')
        rx_pending_sz = self.ramdump.read_structure_field(
            vchan_addr, 'struct virtual_channel', 'rx_pending_sz')
        rx_inflight = self.ramdump.read_structure_field(
            vchan_addr, 'struct virtual_channel', 'rx_inflight')

        lid_seq, lid_dom, lid_mmid = _decode_vcid(vchan_id or 0)
        rid_seq, rid_dom, rid_mmid = _decode_vcid(otherend_id or 0)

        out.write('    vchan[{}] @ 0x{:x}  '
                  'id=0x{:08x}(seq={} dom={} mmid={})  '
                  'otherend_id=0x{:08x}(seq={} dom={} mmid={})  '
                  'session_id=0x{:x}  closed={}  otherend_closed={}\n'.format(
                      index, vchan_addr,
                      vchan_id or 0, lid_seq, lid_dom, lid_mmid,
                      otherend_id or 0, rid_seq, rid_dom, rid_mmid,
                      session_id or 0, closed or 0, otherend_closed or 0))
        out.write('             tx_cnt={}  rx_cnt={}  '
                  'rx_pending_cnt={}  rx_pending_cnt_peak={}  '
                  'rx_pending_sz={}  rx_inflight={}\n'.format(
                      tx_cnt or 0, rx_cnt or 0,
                      rx_pending_cnt or 0, rx_pending_cnt_peak or 0,
                      rx_pending_sz or 0, rx_inflight or 0))

    # ------------------------------------------------------------------ #
    # uhab_context (HAB client contexts)                                   #
    # ------------------------------------------------------------------ #

    _IMP_STATE = ['INIT', 'IMPORTING', 'IMPORTED', 'UNIMPORTING']

    _MMID_NAMES = {
        101: 'MM_AUD_1',        102: 'MM_AUD_2',        103: 'MM_AUD_3',
        104: 'MM_AUD_4',
        201: 'MM_CAM_1',        202: 'MM_CAM_2',
        301: 'MM_DISP_1',       302: 'MM_DISP_2',       303: 'MM_DISP_3',
        304: 'MM_DISP_4',       305: 'MM_DISP_5',
        401: 'MM_GFX',
        501: 'MM_VID',          502: 'MM_VID_2',        503: 'MM_VID_3',
        601: 'MM_MISC',
        701: 'MM_QCPE_VM1',
        801: 'MM_CLK_VM1',      802: 'MM_CLK_VM2',
        901: 'MM_FDE_1',
        1001: 'MM_BUFFERQ_1',
        1101: 'MM_DATA_NETWORK_1', 1102: 'MM_DATA_NETWORK_2',
        1201: 'MM_HSI2S_1',
        1301: 'MM_XVM_1',       1302: 'MM_XVM_2',       1303: 'MM_XVM_3',
        1401: 'MM_VNW_1',
        1501: 'MM_EXT_1',       1502: 'MM_EXT_2',       1503: 'MM_EXT_3',
        1601: 'MM_GPCE_1',
        1701: 'MM_SOCCP_1',
        1801: 'MM_DPRX_1',      1802: 'MM_DPRX_2',
        1901: 'MM_EVA_1',
    }

    def _dump_uctx_list(self, out, hab_addr):
        if hab_addr is None:
            return

        uctx_list_offset = self.ramdump.field_offset(
            'struct hab_driver', 'uctx_list')
        node_offset = self.ramdump.field_offset('struct uhab_context', 'node')

        ctx_list = list(ListWalker(self.ramdump,
                                   hab_addr + uctx_list_offset,
                                   node_offset))

        out.write('\n--- contexts (uctx_list) ---\n')
        if not ctx_list:
            out.write('  (no contexts)\n')
            return

        # Cross-context imp_whse summary; cache groups to avoid re-traversal
        global_imp = {}  # mmid -> {'ctx_set': set, 'total_pages': int}
        imp_cache = {}   # ctx_addr -> groups dict
        for ctx_addr in ctx_list:
            groups = self._collect_imp_groups(ctx_addr)
            imp_cache[ctx_addr] = groups
            for mmid, entries in groups.items():
                g = global_imp.setdefault(
                    mmid, {'ctx_set': set(), 'total_pages': 0})
                g['ctx_set'].add(ctx_addr)
                g['total_pages'] += sum(e.payload_count or 0 for e in entries)

        out.write('\nimp_whse summary (all contexts):\n')
        out.write('  {:<8} {:<20} {:<12} {:<14} {}\n'.format(
            'MMID', 'name', 'ctx_count', 'total_pages', 'total_size'))
        out.write('  {}\n'.format('-' * 62))
        for mmid in sorted(global_imp.keys()):
            info = global_imp[mmid]
            total_pages = info['total_pages']
            out.write('  {:<8} {:<20} {:<12} {:<14} {} KB\n'.format(
                mmid, self._MMID_NAMES.get(mmid, 'unknown'),
                len(info['ctx_set']), total_pages, total_pages * 4))

        # Per-context detail
        for idx, ctx_addr in enumerate(ctx_list):
            out.write('\n[ctx {}] {}\n'.format(idx, '-' * 60))
            self._dump_ctx(out, ctx_addr, idx, imp_cache[ctx_addr])

    def _dump_ctx(self, out, ctx_addr, idx, imp_groups):
        owner        = self.ramdump.read_structure_field(
            ctx_addr, 'struct uhab_context', 'owner')
        kernel       = self.ramdump.read_structure_field(
            ctx_addr, 'struct uhab_context', 'kernel')
        closing      = self.ramdump.read_structure_field(
            ctx_addr, 'struct uhab_context', 'closing')
        vcnt         = self.ramdump.read_structure_field(
            ctx_addr, 'struct uhab_context', 'vcnt')
        export_total = self.ramdump.read_structure_field(
            ctx_addr, 'struct uhab_context', 'export_total')
        import_total = self.ramdump.read_structure_field(
            ctx_addr, 'struct uhab_context', 'import_total')
        pending_cnt  = self.ramdump.read_structure_field(
            ctx_addr, 'struct uhab_context', 'pending_cnt')

        out.write('ctx[{}] @ 0x{:x}  tid={}  kernel={}  closing={}  '
                  'vcnt={}  export_total={}  import_total={}  '
                  'pending_cnt={}\n'.format(
                      idx, ctx_addr,
                      owner or 0, kernel or 0, closing or 0,
                      vcnt or 0, export_total or 0, import_total or 0,
                      pending_cnt or 0))

        self._dump_exp_whse(out, ctx_addr)
        out.write('\n')
        self._dump_imp_whse(out, ctx_addr, owner or 0, imp_groups)

    def _dump_exp_whse(self, out, ctx_addr):
        exp_whse_offset = self.ramdump.field_offset(
            'struct uhab_context', 'exp_whse')
        node_offset = self.ramdump.field_offset('struct export_desc', 'node')

        # Collect all entries first so we can group by MMID
        groups = {}  # mmid -> list of field tuples
        exp_super_exp_offset = self.ramdump.field_offset(
            'struct export_desc_super', 'exp')
        if exp_super_exp_offset is None:
            out.write('  exp_whse: (field offset unavailable)\n')
            return
        for exp_addr in ListWalker(self.ramdump,
                                   ctx_addr + exp_whse_offset,
                                   node_offset):
            # exp_whse links export_desc.node; every entry is always allocated
            # as part of an export_desc_super (by hab_mem_export), so
            # subtracting the 'exp' field offset recovers the containing struct.
            exp_super_addr = exp_addr - exp_super_exp_offset
            export_id     = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'export_id')
            vcid_local    = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'vcid_local')
            vcid_remote   = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'vcid_remote')
            domid_local   = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'domid_local')
            domid_remote  = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'domid_remote')
            payload_count = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'payload_count')
            readonly      = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'readonly')
            remote_imported = self.ramdump.read_structure_field(
                exp_super_addr, 'struct export_desc_super', 'remote_imported')

            _, _, mmid = _decode_vcid(vcid_local or 0)
            groups.setdefault(mmid, []).append(_ExpEntry(
                exp_addr, export_id, vcid_local, vcid_remote,
                domid_local, domid_remote, payload_count, readonly,
                remote_imported))

        out.write('  exp_whse:\n')
        if not groups:
            out.write('    (empty)\n')
            return

        # Summary table
        out.write('    {:<8} {:<20} {:<8} {:<14} {:<14} {}\n'.format(
            'MMID', 'name', 'count', 'total_pages', 'total_size',
            'remote_imp_size'))
        out.write('    {}\n'.format('-' * 74))
        for mmid in sorted(groups.keys()):
            entries = groups[mmid]
            total_pages = sum(e.payload_count or 0 for e in entries)
            rimp_pages  = sum(e.payload_count or 0 for e in entries if e.remote_imported)
            out.write('    {:<8} {:<20} {:<8} {:<14} {:<14} {} KB\n'.format(
                mmid, self._MMID_NAMES.get(mmid, 'unknown'),
                len(entries), total_pages, '{} KB'.format(total_pages * 4),
                rimp_pages * 4))
        out.write('\n')

        # Per-MMID detail
        for mmid in sorted(groups.keys()):
            entries = groups[mmid]
            total_pages = sum(e.payload_count or 0 for e in entries)
            out.write('    mmid={}({})  count={}  total={} pages ({} KB)\n'.format(
                mmid, self._MMID_NAMES.get(mmid, 'unknown'),
                len(entries), total_pages, total_pages * 4))
            for idx, (exp_addr, export_id, vcid_local, vcid_remote,
                      domid_local, domid_remote, payload_count, readonly,
                      remote_imported) \
                    in enumerate(entries):
                out.write('      exp[{}] @ 0x{:x}  export_id={}  '
                          'vcid_local=0x{:x}  vcid_remote=0x{:x}  '
                          'domid_local={}  domid_remote={}  '
                          'payload_count={}  readonly={}  '
                          'remote_imported={}\n'.format(
                              idx, exp_addr,
                              export_id or 0,
                              vcid_local or 0, vcid_remote or 0,
                              domid_local or 0, domid_remote or 0,
                              payload_count or 0, readonly or 0,
                              remote_imported or 0))
            out.write('\n')

    def _collect_imp_groups(self, ctx_addr):
        """Return imp_whse entries grouped by MMID without producing output."""
        imp_whse_offset = self.ramdump.field_offset(
            'struct uhab_context', 'imp_whse')
        node_offset = self.ramdump.field_offset(
            'struct export_desc_super', 'node')
        exp_offset  = self.ramdump.field_offset(
            'struct export_desc_super', 'exp')

        if None in (imp_whse_offset, node_offset, exp_offset):
            return {}

        groups = {}
        for rb_node_addr in RbTree(self.ramdump, ctx_addr + imp_whse_offset):
            exp_super_addr = rb_node_addr - node_offset
            exp_addr       = exp_super_addr + exp_offset

            import_state = self.ramdump.read_structure_field(
                exp_super_addr, 'struct export_desc_super', 'import_state')
            payload_size = self.ramdump.read_structure_field(
                exp_super_addr, 'struct export_desc_super', 'payload_size')
            is_loopback  = self.ramdump.read_structure_field(
                exp_super_addr, 'struct export_desc_super', 'is_loopback')

            export_id     = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'export_id')
            vcid_local    = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'vcid_local')
            vcid_remote   = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'vcid_remote')
            domid_local   = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'domid_local')
            domid_remote  = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'domid_remote')
            payload_count = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'payload_count')
            readonly      = self.ramdump.read_structure_field(
                exp_addr, 'struct export_desc', 'readonly')

            _, _, mmid = _decode_vcid(vcid_local or 0)
            groups.setdefault(mmid, []).append(_ImpEntry(
                exp_super_addr, export_id, vcid_local, vcid_remote,
                domid_local, domid_remote, payload_count, readonly,
                import_state, payload_size, is_loopback))
        return groups

    def _dump_imp_whse(self, out, ctx_addr, owner_tid, groups):
        out.write('  imp_whse (tid={}):\n'.format(owner_tid))
        if not groups:
            out.write('    (empty)\n')
            return

        # Summary table
        out.write('    {:<8} {:<20} {:<8} {:<14} {}\n'.format(
            'MMID', 'name', 'count', 'total_pages', 'total_size'))
        out.write('    {}\n'.format('-' * 58))
        for mmid in sorted(groups.keys()):
            entries = groups[mmid]
            total_pages = sum(e.payload_count or 0 for e in entries)
            out.write('    {:<8} {:<20} {:<8} {:<14} {} KB\n'.format(
                mmid, self._MMID_NAMES.get(mmid, 'unknown'),
                len(entries), total_pages, total_pages * 4))
        out.write('\n')

        # Per-MMID detail
        for mmid in sorted(groups.keys()):
            entries = groups[mmid]
            total_pages = sum(e.payload_count or 0 for e in entries)
            out.write('    mmid={}({})  count={}  total={} pages ({} KB)\n'.format(
                mmid, self._MMID_NAMES.get(mmid, 'unknown'),
                len(entries), total_pages, total_pages * 4))
            for idx, (exp_super_addr, export_id, vcid_local, vcid_remote,
                      domid_local, domid_remote, payload_count, readonly,
                      import_state, payload_size,
                      is_loopback) in enumerate(entries):
                state_str = (self._IMP_STATE[import_state]
                             if import_state is not None
                             and 0 <= import_state < len(self._IMP_STATE)
                             else str(import_state))
                out.write('      imp[{}] @ 0x{:x}  export_id={}  '
                          'vcid_local=0x{:x}  vcid_remote=0x{:x}  '
                          'domid_local={}  domid_remote={}  '
                          'payload_count={}  payload_size={}  '
                          'readonly={}  import_state={}  '
                          'is_loopback={}\n'.format(
                              idx, exp_super_addr,
                              export_id or 0,
                              vcid_local or 0, vcid_remote or 0,
                              domid_local or 0, domid_remote or 0,
                              payload_count or 0, payload_size or 0,
                              readonly or 0, state_str,
                              is_loopback or 0))
            out.write('\n')
