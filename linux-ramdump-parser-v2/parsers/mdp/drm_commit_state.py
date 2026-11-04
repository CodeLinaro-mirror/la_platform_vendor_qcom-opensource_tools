# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: GPL-2.0-only

from parser_util import RamParser
from print_out import print_out_str
from linux_list import ListWalker
from parsers.mdp import PacAwareRamDump


REPORT_SEPARATOR = '=' * 100
DRM_FORMAT_MAX_PLANES = 4
MAX_REPORTED_VMAS = 8
MAX_REPORTED_CONNECTORS = 8


SSPP_NAMES = {
    0: 'SSPP_NONE',
    1: 'SSPP_VIG0', 2: 'SSPP_VIG1', 3: 'SSPP_VIG2', 4: 'SSPP_VIG3',
    5: 'SSPP_VIG4', 6: 'SSPP_VIG5', 7: 'SSPP_VIG6', 8: 'SSPP_VIG7',
    9: 'SSPP_DMA0', 10: 'SSPP_DMA1', 11: 'SSPP_DMA2', 12: 'SSPP_DMA3',
    13: 'SSPP_DMA4', 14: 'SSPP_DMA5',
    15: 'SSPP_CSC0', 16: 'SSPP_CSC1',
}
PLANE_TYPE_NAMES = {0: 'OVERLAY', 1: 'PRIMARY', 2: 'CURSOR'}
CONNECTOR_TYPE_NAMES = {
    0: 'Unknown', 1: 'VGA', 2: 'DVII', 3: 'DVID', 4: 'DVIA',
    5: 'Composite', 6: 'SVIDEO', 7: 'LVDS', 8: 'Component',
    9: '9PinDIN', 10: 'DisplayPort', 11: 'HDMIA', 12: 'HDMIB',
    13: 'TV', 14: 'eDP', 15: 'VIRTUAL', 16: 'DSI', 17: 'DPI',
    18: 'WRITEBACK', 19: 'SPI', 20: 'USB',
}
CONNECTOR_STATUS = {0: 'connected', 1: 'disconnected', 2: 'unknown'}
SDE_STAGE_NAMES = {
    0: 'SDE_STAGE_BASE', 1: 'SDE_STAGE_0', 2: 'SDE_STAGE_1',
    3: 'SDE_STAGE_2', 4: 'SDE_STAGE_3', 5: 'SDE_STAGE_4',
    6: 'SDE_STAGE_5', 7: 'SDE_STAGE_6',
}


class DrmCommitStateParser(RamParser):
    def __init__(self, dump):
        super(DrmCommitStateParser, self).__init__(dump)
        self.ramdump = PacAwareRamDump(dump)

    def _offset(self, struct_name, field_name, fallback=None):
        offset = self.ramdump.field_offset(struct_name, field_name)
        return fallback if offset is None else offset

    def _read_u32(self, address, offset):
        return self.ramdump.read_u32(address + offset) if offset is not None else None

    def _read_u16(self, address, offset):
        return self.ramdump.read_u16(address + offset) if offset is not None else None

    def _read_u8(self, address, offset):
        return self.ramdump.read_byte(address + offset) if offset is not None else None

    def dump_commit_state(self):
        """
        Walk the live DRM object lists and dump the commit state at crash time
        into display_info/drm_commit_state.txt.

        Does NOT use drm_atomic_state (which may be NULL or stale at crash time).
        Instead reads the committed state directly from each object's own ->state
        pointer, which always reflects the last successfully applied commit:
          plane->state     -> drm_plane_state  -> sde_plane_state (container_of)
          crtc->state      -> drm_crtc_state   -> sde_crtc_state  (container_of)
          connector->state -> drm_connector_state

        Chain walked to enumerate objects:
          sde_dbg_base (global struct, reliable symbol)
            .dev           -> struct device *  (platform_device.dev)
            .driver_data   -> struct drm_device *
            .dev_private   -> struct msm_drm_private *
            .kms           -> struct msm_kms * -> struct sde_kms * (container_of)
            .mode_config
              -> plane_list     (struct drm_plane,     via drm_plane.head)
              -> crtc_list      (struct drm_crtc,      via drm_crtc.head)
              -> connector_list (struct drm_connector, via drm_connector.head)
        """
        print_out_str("Starting dump_commit_state")

        try:
            out = self.ramdump.open_file('display_info/drm_commit_state.txt', 'w')
        except Exception as ex:
            print_out_str("dump_commit_state: cannot open output: {}".format(ex))
            return

        try:
            out.write("{}\n".format(REPORT_SEPARATOR))
            out.write("DRM COMMIT STATE DUMP\n")
            out.write("{}\n\n".format(REPORT_SEPARATOR))

            mode_config_addr = self._locate_mode_config(out)
            if mode_config_addr is None:
                return

            self._dump_planes(out, mode_config_addr)
            self._dump_crtcs(out, mode_config_addr)
            self._dump_connectors(out, mode_config_addr)

            out.write("{}\n".format(REPORT_SEPARATOR))
            out.write("END OF DRM COMMIT STATE DUMP\n")
            out.write("{}\n".format(REPORT_SEPARATOR))

        except Exception as ex:
            out.write("\nEXCEPTION during dump_commit_state: {}\n".format(ex))
            import traceback
            out.write(traceback.format_exc())
            print_out_str("dump_commit_state: exception: {}".format(ex))
        finally:
            try:
                out.close()
            except Exception as ex:
                print_out_str(
                    "dump_commit_state: failed to close output: {}".format(ex))
            else:
                print_out_str(
                    "dump_commit_state: wrote display_info/drm_commit_state.txt")

    def _dump_planes(self, out, mode_config_addr):
        PTR = self.ramdump.sizeof('void *') or 8
        _foff = self._offset

        # ------------------------------------------------------------------
        # 2. Walk plane_list
        # ------------------------------------------------------------------
        plane_list_off = _foff('struct drm_mode_config', 'plane_list')
        plane_head_off = _foff('struct drm_plane', 'head')
        if plane_list_off is None or plane_head_off is None:
            out.write("WARNING: cannot resolve plane_list offsets, skipping planes.\n\n")
        else:
            plane_list_addr = mode_config_addr + plane_list_off
            out.write("{}\n".format(REPORT_SEPARATOR))
            out.write("PLANES  (drm_mode_config.plane_list @ 0x{:x})\n".format(
                plane_list_addr))
            out.write("{}\n\n".format(REPORT_SEPARATOR))

            plane_idx = 0
            for plane_addr in ListWalker(self.ramdump, plane_list_addr,
                                         plane_head_off):
                self._dump_plane(out, plane_addr, plane_idx)
                plane_idx += 1

    def _dump_crtcs(self, out, mode_config_addr):
        PTR = self.ramdump.sizeof('void *') or 8
        _foff = self._offset

        # ------------------------------------------------------------------
        # 3. Walk crtc_list
        # ------------------------------------------------------------------
        crtc_list_off = _foff('struct drm_mode_config', 'crtc_list')
        crtc_head_off = _foff('struct drm_crtc', 'head')
        if crtc_list_off is None or crtc_head_off is None:
            out.write("WARNING: cannot resolve crtc_list offsets, skipping crtcs.\n\n")
        else:
            crtc_list_addr = mode_config_addr + crtc_list_off
            out.write("{}\n".format(REPORT_SEPARATOR))
            out.write("CRTCs  (drm_mode_config.crtc_list @ 0x{:x})\n".format(
                crtc_list_addr))
            out.write("{}\n\n".format(REPORT_SEPARATOR))

            crtc_idx = 0
            for crtc_addr in ListWalker(self.ramdump, crtc_list_addr,
                                        crtc_head_off):
                self._dump_crtc(out, crtc_addr, crtc_idx)
                crtc_idx += 1

    def _dump_connectors(self, out, mode_config_addr):
        PTR = self.ramdump.sizeof('void *') or 8
        _foff = self._offset

        # ------------------------------------------------------------------
        # 4. Walk connector_list
        # ------------------------------------------------------------------
        conn_list_off = _foff('struct drm_mode_config', 'connector_list')
        conn_head_off = _foff('struct drm_connector', 'head')
        if conn_list_off is None or conn_head_off is None:
            out.write("WARNING: cannot resolve connector_list offsets, "
                      "skipping connectors.\n\n")
        else:
            conn_list_addr = mode_config_addr + conn_list_off
            out.write("{}\n".format(REPORT_SEPARATOR))
            out.write("CONNECTORS  (drm_mode_config.connector_list @ 0x{:x})\n".format(
                conn_list_addr))
            out.write("{}\n\n".format(REPORT_SEPARATOR))

            conn_idx = 0
            for conn_addr in ListWalker(self.ramdump, conn_list_addr,
                                        conn_head_off):
                self._dump_connector(out, conn_addr, conn_idx)
                conn_idx += 1

    def _dump_plane(self, out, plane_addr, plane_idx):
        _foff = self._offset

        plane_type_off = _foff('struct drm_plane', 'type')
        plane_state_off = _foff('struct drm_plane', 'state')
        plane_name_off = _foff('struct drm_plane', 'name')

        plane_type = (self.ramdump.read_u32(plane_addr + plane_type_off)
                      if plane_type_off is not None else None)
        plane_state_ptr = (self.ramdump.read_pointer(plane_addr + plane_state_off)
                           if plane_state_off is not None else None)
        plane_name = (self.ramdump.read_cstring(plane_addr + plane_name_off, 32)
                      if plane_name_off is not None else None)

        sde_pipe_off = _foff('struct sde_plane', 'pipe')
        sde_pipename_off = _foff('struct sde_plane', 'pipe_name')
        sde_is_virt_off = _foff('struct sde_plane', 'is_virtual')

        sde_pipe = (self.ramdump.read_u32(plane_addr + sde_pipe_off)
                    if sde_pipe_off is not None else None)
        sde_pipe_name = (self.ramdump.read_cstring(
            plane_addr + sde_pipename_off, 32)
            if sde_pipename_off is not None else None)
        sde_is_virtual = (self.ramdump.read_byte(plane_addr + sde_is_virt_off)
                          if sde_is_virt_off is not None else None)

        type_str = PLANE_TYPE_NAMES.get(plane_type, str(plane_type))
        pipe_str = (SSPP_NAMES.get(sde_pipe, 'SSPP_{}'.format(sde_pipe))
                    if sde_pipe is not None else 'N/A')

        out.write("  [PLANE {:2d}] (struct drm_plane *)  @ 0x{:x}"
                  "  (struct sde_plane *) @ 0x{:x}\n".format(
                      plane_idx, plane_addr, plane_addr))
        out.write("    name         : {}\n".format(plane_name or 'N/A'))
        out.write("    type         : {} ({})\n".format(type_str, plane_type))
        out.write("    pipe         : {}  ({})\n".format(pipe_str, sde_pipe))
        out.write("    pipe_name    : {}\n".format(sde_pipe_name or 'N/A'))
        out.write("    is_virtual   : {}\n".format(
            bool(sde_is_virtual) if sde_is_virtual is not None else 'N/A'))
        out.write("    drm state ptr: {}\n".format(
            "0x{:x}".format(plane_state_ptr) if plane_state_ptr else "NULL"))

        if plane_state_ptr:
            self._dump_plane_state(out, plane_state_ptr)

        out.write("\n")

    def _dump_crtc(self, out, crtc_addr, crtc_idx):
        _foff = self._offset

        crtc_name_off = _foff('struct drm_crtc', 'name')
        crtc_enabled_off = _foff('struct drm_crtc', 'enabled')
        crtc_state_off = _foff('struct drm_crtc', 'state')

        crtc_name = (self.ramdump.read_cstring(
            crtc_addr + crtc_name_off, 32)
            if crtc_name_off is not None else None)
        crtc_enabled = (self.ramdump.read_byte(
            crtc_addr + crtc_enabled_off)
            if crtc_enabled_off is not None else None)
        crtc_state_ptr = (self.ramdump.read_pointer(
            crtc_addr + crtc_state_off)
            if crtc_state_off is not None else None)

        sde_crtc_name_off = _foff('struct sde_crtc', 'name')
        sde_num_ctls_off = _foff('struct sde_crtc', 'num_ctls')
        sde_num_mixers_off = _foff('struct sde_crtc', 'num_mixers')
        sde_crtc_enabled_off = _foff('struct sde_crtc', 'enabled')
        sde_play_count_off = _foff('struct sde_crtc', 'play_count')
        sde_frame_pend_off = _foff('struct sde_crtc', 'frame_pending')

        sde_crtc_name = (self.ramdump.read_cstring(
            crtc_addr + sde_crtc_name_off, 32)
            if sde_crtc_name_off is not None else None)
        sde_num_ctls = (self.ramdump.read_u32(crtc_addr + sde_num_ctls_off)
                        if sde_num_ctls_off is not None else None)
        sde_num_mixers = (self.ramdump.read_u32(crtc_addr + sde_num_mixers_off)
                          if sde_num_mixers_off is not None else None)
        sde_crtc_en = (self.ramdump.read_byte(crtc_addr + sde_crtc_enabled_off)
                       if sde_crtc_enabled_off is not None else None)
        sde_play_count = (self.ramdump.read_u64(crtc_addr + sde_play_count_off)
                          if sde_play_count_off is not None else None)
        sde_frame_pend = (self.ramdump.read_u32(crtc_addr + sde_frame_pend_off)
                          if sde_frame_pend_off is not None else None)

        out.write("  [CRTC {:2d}] (struct drm_crtc *)  @ 0x{:x}"
                  "  (struct sde_crtc *) @ 0x{:x}\n".format(
                      crtc_idx, crtc_addr, crtc_addr))
        out.write("    drm name     : {}\n".format(crtc_name or 'N/A'))
        out.write("    sde name     : {}\n".format(sde_crtc_name or 'N/A'))
        out.write("    drm enabled  : {}\n".format(
            bool(crtc_enabled) if crtc_enabled is not None else 'N/A'))
        out.write("    sde enabled  : {}\n".format(
            bool(sde_crtc_en) if sde_crtc_en is not None else 'N/A'))
        out.write("    num_ctls     : {}  num_mixers: {}\n".format(
            sde_num_ctls, sde_num_mixers))
        out.write("    play_count   : {}\n".format(sde_play_count))
        out.write("    frame_pending: {}\n".format(sde_frame_pend))
        out.write("    state ptr    : {}\n".format(
            "0x{:x}".format(crtc_state_ptr) if crtc_state_ptr else "NULL"))

        if crtc_state_ptr:
            self._dump_crtc_state(out, crtc_state_ptr)

        out.write("\n")

    def _dump_connector(self, out, conn_addr, conn_idx):
        _foff = self._offset

        conn_type_off = _foff('struct drm_connector', 'connector_type')
        conn_status_off = _foff('struct drm_connector', 'status')
        conn_state_off = _foff('struct drm_connector', 'state')
        conn_name_off = _foff('struct drm_connector', 'name')

        conn_type = (self.ramdump.read_u32(conn_addr + conn_type_off)
                     if conn_type_off is not None else None)
        conn_status = (self.ramdump.read_u32(conn_addr + conn_status_off)
                       if conn_status_off is not None else None)
        conn_state_ptr = (self.ramdump.read_pointer(
            conn_addr + conn_state_off)
            if conn_state_off is not None else None)
        conn_name = (self.ramdump.read_cstring(conn_addr + conn_name_off, 64)
                     if conn_name_off is not None else None)

        sde_conn_name_off = _foff('struct sde_connector', 'name')
        sde_dpms_off = _foff('struct sde_connector', 'dpms_mode')
        sde_lp_off = _foff('struct sde_connector', 'lp_mode')
        sde_panel_dead_off = _foff('struct sde_connector', 'panel_dead')
        sde_encoder_off = _foff('struct sde_connector', 'encoder')
        sde_display_off = _foff('struct sde_connector', 'display')

        sde_conn_name = (self.ramdump.read_cstring(
            conn_addr + sde_conn_name_off, 64)
            if sde_conn_name_off is not None else None)
        sde_dpms = (self.ramdump.read_u32(conn_addr + sde_dpms_off)
                    if sde_dpms_off is not None else None)
        sde_lp = (self.ramdump.read_u32(conn_addr + sde_lp_off)
                  if sde_lp_off is not None else None)
        sde_panel_dead = (self.ramdump.read_byte(conn_addr + sde_panel_dead_off)
                          if sde_panel_dead_off is not None else None)
        sde_encoder_ptr = (self.ramdump.read_pointer(conn_addr + sde_encoder_off)
                           if sde_encoder_off is not None else None)
        sde_display_ptr = (self.ramdump.read_pointer(conn_addr + sde_display_off)
                           if sde_display_off is not None else None)

        type_str = CONNECTOR_TYPE_NAMES.get(conn_type,
                                            'type_{}'.format(conn_type))
        status_str = CONNECTOR_STATUS.get(conn_status,
                                          'status_{}'.format(conn_status))

        out.write("  [CONN {:2d}] (struct drm_connector *) @ 0x{:x}"
                  "  (struct sde_connector *) @ 0x{:x}\n".format(
                      conn_idx, conn_addr, conn_addr))
        out.write("    drm name     : {}\n".format(conn_name or 'N/A'))
        out.write("    sde name     : {}\n".format(sde_conn_name or 'N/A'))
        out.write("    type         : {} ({})\n".format(type_str, conn_type))
        out.write("    status       : {} ({})\n".format(status_str, conn_status))
        out.write("    dpms_mode    : {}\n".format(sde_dpms))
        out.write("    lp_mode      : {}\n".format(sde_lp))
        out.write("    panel_dead   : {}\n".format(
            bool(sde_panel_dead) if sde_panel_dead is not None else 'N/A'))
        out.write("    encoder ptr  : {}\n".format(
            "0x{:x}".format(sde_encoder_ptr) if sde_encoder_ptr else "NULL"))
        out.write("    display ptr  : {}\n".format(
            "0x{:x}".format(sde_display_ptr) if sde_display_ptr else "NULL"))
        out.write("    state ptr    : {}\n".format(
            "0x{:x}".format(conn_state_ptr) if conn_state_ptr else "NULL"))

        if conn_state_ptr:
            self._dump_connector_state(out, conn_state_ptr)

        out.write("\n")

    def _dump_plane_state(self, out, plane_state_ptr):
        PTR = self.ramdump.sizeof('void *') or 8
        _foff = self._offset

        ps_crtc_off = _foff('struct drm_plane_state', 'crtc')
        ps_fb_off = _foff('struct drm_plane_state', 'fb')
        ps_crtc_x_off = _foff('struct drm_plane_state', 'crtc_x')
        ps_crtc_y_off = _foff('struct drm_plane_state', 'crtc_y')
        ps_crtc_w_off = _foff('struct drm_plane_state', 'crtc_w')
        ps_crtc_h_off = _foff('struct drm_plane_state', 'crtc_h')
        ps_src_x_off = _foff('struct drm_plane_state', 'src_x')
        ps_src_y_off = _foff('struct drm_plane_state', 'src_y')
        ps_src_w_off = _foff('struct drm_plane_state', 'src_w')
        ps_src_h_off = _foff('struct drm_plane_state', 'src_h')
        ps_alpha_off = _foff('struct drm_plane_state', 'alpha')
        ps_zpos_off = _foff('struct drm_plane_state', 'zpos')
        ps_rot_off = _foff('struct drm_plane_state', 'rotation')
        ps_visible_off = _foff('struct drm_plane_state', 'visible')

        ps_crtc_ptr = (self.ramdump.read_pointer(
            plane_state_ptr + ps_crtc_off)
            if ps_crtc_off is not None else None)
        ps_fb_ptr = (self.ramdump.read_pointer(
            plane_state_ptr + ps_fb_off)
            if ps_fb_off is not None else None)

        _r32 = self._read_u32
        _r16 = self._read_u16
        _r8 = self._read_u8

        # Compute sde_plane_state pointer and aspace early so
        # the fb/VMA block can use them for the active-VMA marker.
        sde_ps_base_off_early = _foff('struct sde_plane_state', 'base')
        sde_ps_ptr_early = (plane_state_ptr - sde_ps_base_off_early
                            if sde_ps_base_off_early is not None
                            else plane_state_ptr)
        sde_aspace_off = _foff('struct sde_plane_state', 'aspace')
        sde_ps_aspace = (self.ramdump.read_pointer(
            sde_ps_ptr_early + sde_aspace_off)
            if sde_aspace_off is not None else None)

        crtc_x = _r32(plane_state_ptr, ps_crtc_x_off)
        crtc_y = _r32(plane_state_ptr, ps_crtc_y_off)
        crtc_w = _r32(plane_state_ptr, ps_crtc_w_off)
        crtc_h = _r32(plane_state_ptr, ps_crtc_h_off)
        src_x = _r32(plane_state_ptr, ps_src_x_off)
        src_y = _r32(plane_state_ptr, ps_src_y_off)
        src_w = _r32(plane_state_ptr, ps_src_w_off)
        src_h = _r32(plane_state_ptr, ps_src_h_off)
        alpha = _r16(plane_state_ptr, ps_alpha_off)
        zpos = _r32(plane_state_ptr, ps_zpos_off)
        rot = _r32(plane_state_ptr, ps_rot_off)
        vis = _r8(plane_state_ptr, ps_visible_off)

        out.write("    --- drm_plane_state @ 0x{:x}\n".format(
            plane_state_ptr))
        out.write("      crtc ptr   : {}\n".format(
            "0x{:x}".format(ps_crtc_ptr) if ps_crtc_ptr else "NULL"))
        out.write("      fb ptr     : {}\n".format(
            "0x{:x}".format(ps_fb_ptr) if ps_fb_ptr else "NULL"))
        out.write("      visible    : {}\n".format(
            bool(vis) if vis is not None else 'N/A'))
        out.write("      crtc rect  : x={} y={} w={} h={}\n".format(
            crtc_x, crtc_y, crtc_w, crtc_h))
        out.write("      src  rect  : x={} y={} w={} h={}"
                  "  (16.16 fixed)\n".format(src_x, src_y, src_w, src_h))
        out.write("      alpha      : 0x{:04x}  zpos={}"
                  "  rotation=0x{:x}\n".format(
                      alpha if alpha is not None else 0,
                      zpos, rot if rot is not None else 0))

        if ps_fb_ptr:
            self._dump_framebuffer(out, ps_fb_ptr, sde_ps_aspace)

        # sde_plane_state: container_of(drm_plane_state, sde_plane_state, base)
        sde_ps_base_off = _foff('struct sde_plane_state', 'base')
        sde_ps_ptr = (plane_state_ptr - sde_ps_base_off
                      if sde_ps_base_off is not None
                      else plane_state_ptr)

        sde_stage_off = _foff('struct sde_plane_state', 'stage')
        sde_dirty_off = _foff('struct sde_plane_state', 'dirty')
        sde_pending_off = _foff('struct sde_plane_state', 'pending')
        sde_mrect_idx_off = _foff('struct sde_plane_state', 'multirect_index')
        sde_mrect_mode_off = _foff('struct sde_plane_state', 'multirect_mode')
        sde_rotation_off = _foff('struct sde_plane_state', 'rotation')
        sde_pipe_order_off = _foff('struct sde_plane_state', 'pipe_order_flags')
        sde_layout_off = _foff('struct sde_plane_state', 'layout')
        sde_const_alpha_off = _foff('struct sde_plane_state', 'const_alpha_en')
        sde_defer_off = _foff('struct sde_plane_state', 'defer_prepare_fb')

        sde_stage = _r32(sde_ps_ptr, sde_stage_off)
        sde_dirty = _r32(sde_ps_ptr, sde_dirty_off)
        sde_pending = _r8(sde_ps_ptr, sde_pending_off)
        sde_mrect_idx = _r32(sde_ps_ptr, sde_mrect_idx_off)
        sde_mrect_mode = _r32(sde_ps_ptr, sde_mrect_mode_off)
        sde_rotation = _r32(sde_ps_ptr, sde_rotation_off)
        sde_pipe_order = _r32(sde_ps_ptr, sde_pipe_order_off)
        sde_layout = _r32(sde_ps_ptr, sde_layout_off)
        sde_const_alpha = _r8(sde_ps_ptr, sde_const_alpha_off)
        sde_defer = _r8(sde_ps_ptr, sde_defer_off)

        stage_str = (SDE_STAGE_NAMES.get(sde_stage,
                                         'SDE_STAGE_{}'.format(sde_stage))
                     if sde_stage is not None else 'N/A')

        out.write("    --- sde_plane_state @ 0x{:x}\n".format(sde_ps_ptr))
        out.write("      stage          : {} ({})\n".format(
            stage_str, sde_stage))
        out.write("      dirty          : 0x{:08x}\n".format(
            sde_dirty if sde_dirty is not None else 0))
        out.write("      pending        : {}\n".format(
            bool(sde_pending) if sde_pending is not None else 'N/A'))
        out.write("      const_alpha_en : {}\n".format(
            bool(sde_const_alpha) if sde_const_alpha is not None else 'N/A'))
        out.write("      defer_prepare  : {}\n".format(
            bool(sde_defer) if sde_defer is not None else 'N/A'))
        out.write("      multirect_index: {}  multirect_mode: {}\n".format(
            sde_mrect_idx, sde_mrect_mode))
        out.write("      rotation       : 0x{:x}\n".format(
            sde_rotation if sde_rotation is not None else 0))
        out.write("      pipe_order_flags: 0x{:x}\n".format(
            sde_pipe_order if sde_pipe_order is not None else 0))
        out.write("      layout         : {}\n".format(sde_layout))

    def _dump_crtc_state(self, out, crtc_state_ptr):
        PTR = self.ramdump.sizeof('void *') or 8
        _foff = self._offset

        cs_enable_off = _foff('struct drm_crtc_state', 'enable')
        cs_active_off = _foff('struct drm_crtc_state', 'active')

        cs_enable = (self.ramdump.read_byte(
            crtc_state_ptr + cs_enable_off)
            if cs_enable_off is not None else None)
        cs_active = (self.ramdump.read_byte(
            crtc_state_ptr + cs_active_off)
            if cs_active_off is not None else None)

        sde_cs_base_off = _foff('struct sde_crtc_state', 'base')
        sde_cs_ptr = (crtc_state_ptr - sde_cs_base_off
                      if sde_cs_base_off is not None
                      else crtc_state_ptr)

        sde_num_conn_off = _foff('struct sde_crtc_state', 'num_connectors')
        sde_bw_ctrl_off = _foff('struct sde_crtc_state', 'bw_control')
        sde_is_ppsplit_off = _foff('struct sde_crtc_state', 'is_ppsplit')
        sde_num_ds_off = _foff('struct sde_crtc_state', 'num_ds')
        sde_num_ds_en_off = _foff('struct sde_crtc_state', 'num_ds_enabled')

        sde_num_conn = (self.ramdump.read_u32(
            sde_cs_ptr + sde_num_conn_off)
            if sde_num_conn_off is not None else None)
        sde_bw_ctrl = (self.ramdump.read_byte(
            sde_cs_ptr + sde_bw_ctrl_off)
            if sde_bw_ctrl_off is not None else None)
        sde_is_ppsplit = (self.ramdump.read_byte(
            sde_cs_ptr + sde_is_ppsplit_off)
            if sde_is_ppsplit_off is not None else None)
        sde_num_ds = (self.ramdump.read_u32(
            sde_cs_ptr + sde_num_ds_off)
            if sde_num_ds_off is not None else None)
        sde_num_ds_en = (self.ramdump.read_u32(
            sde_cs_ptr + sde_num_ds_en_off)
            if sde_num_ds_en_off is not None else None)

        out.write("    --- drm_crtc_state @ 0x{:x}\n".format(
            crtc_state_ptr))
        out.write("      enable         : {}\n".format(
            bool(cs_enable) if cs_enable is not None else 'N/A'))
        out.write("      active         : {}\n".format(
            bool(cs_active) if cs_active is not None else 'N/A'))
        out.write("    --- sde_crtc_state @ 0x{:x}\n".format(sde_cs_ptr))
        out.write("      num_connectors : {}\n".format(sde_num_conn))
        out.write("      bw_control     : {}\n".format(
            bool(sde_bw_ctrl) if sde_bw_ctrl is not None else 'N/A'))
        out.write("      is_ppsplit     : {}\n".format(
            bool(sde_is_ppsplit) if sde_is_ppsplit is not None else 'N/A'))
        out.write("      num_ds         : {}  num_ds_enabled: {}\n".format(
            sde_num_ds, sde_num_ds_en))

        sde_connectors_off = _foff('struct sde_crtc_state', 'connectors')
        if sde_connectors_off is not None and sde_num_conn:
            out.write("      connectors[]:\n")
            for ci in range(min(sde_num_conn, MAX_REPORTED_CONNECTORS)):
                conn_ptr = self.ramdump.read_pointer(
                    sde_cs_ptr + sde_connectors_off + ci * PTR)
                out.write("        [{}] (struct drm_connector *) @ {}\n".format(
                    ci,
                    "0x{:x}".format(conn_ptr) if conn_ptr else "NULL"))

    def _dump_connector_state(self, out, conn_state_ptr):
        PTR = self.ramdump.sizeof('void *') or 8
        _foff = self._offset

        cs_crtc_off = _foff('struct drm_connector_state', 'crtc')
        cs_crtc_ptr = (self.ramdump.read_pointer(
            conn_state_ptr + cs_crtc_off)
            if cs_crtc_off is not None else None)
        out.write("    --- drm_connector_state @ 0x{:x}\n".format(
            conn_state_ptr))
        out.write("      crtc ptr   : {}\n".format(
            "0x{:x}".format(cs_crtc_ptr) if cs_crtc_ptr else "NULL"))

    def _dump_framebuffer(self, out, ps_fb_ptr, sde_ps_aspace):
        PTR = self.ramdump.sizeof('void *') or 8
        _foff = self._offset
        _r32 = self._read_u32

        DRM_FORMAT_MAX_PLANES = 4

        fb_w_off = _foff('struct drm_framebuffer', 'width')
        fb_h_off = _foff('struct drm_framebuffer', 'height')
        fb_fmt_off = _foff('struct drm_framebuffer', 'format')
        fb_mod_off = _foff('struct drm_framebuffer', 'modifier')
        fb_pitches_off = _foff('struct drm_framebuffer', 'pitches')
        fb_offsets_off = _foff('struct drm_framebuffer', 'offsets')
        fb_obj_off = _foff('struct drm_framebuffer', 'obj')

        fb_w = _r32(ps_fb_ptr, fb_w_off)
        fb_h = _r32(ps_fb_ptr, fb_h_off)
        fb_fmt_ptr = (self.ramdump.read_pointer(ps_fb_ptr + fb_fmt_off)
                      if fb_fmt_off is not None else None)
        fb_mod = (self.ramdump.read_u64(ps_fb_ptr + fb_mod_off)
                  if fb_mod_off is not None else None)
        fb_fmt_val = (self.ramdump.read_u32(fb_fmt_ptr)
                      if fb_fmt_ptr else None)

        # drm_format_info.num_planes is at offset 4 (after u32 format)
        fb_num_planes = 1
        if fb_fmt_ptr:
            nplanes_off = _foff('struct drm_format_info', 'num_planes')
            if nplanes_off is not None:
                fb_num_planes = (self.ramdump.read_byte(
                    fb_fmt_ptr + nplanes_off) or 1)
            fb_num_planes = max(1, min(fb_num_planes,
                                       DRM_FORMAT_MAX_PLANES))

        out.write("      --- drm_framebuffer @ 0x{:x}\n".format(
            ps_fb_ptr))
        out.write("        pstate->aspace : {}\n".format(
            "0x{:x}".format(sde_ps_aspace)
            if sde_ps_aspace else "NULL"))
        out.write("        size         : {}x{}\n".format(fb_w, fb_h))
        out.write("        format       : 0x{:08x}  "
                  "(drm_format_info @ {})\n".format(
                      fb_fmt_val if fb_fmt_val is not None else 0,
                      "0x{:x}".format(fb_fmt_ptr) if fb_fmt_ptr else "NULL"))
        out.write("        modifier     : 0x{:016x}\n".format(
            fb_mod if fb_mod is not None else 0))
        out.write("        num_planes   : {}\n".format(fb_num_planes))

        # pitches[], offsets[], obj[] are parallel arrays
        # indexed [0..DRM_FORMAT_MAX_PLANES-1]
        for pi in range(fb_num_planes):
            pitch = (_r32(ps_fb_ptr,
                          fb_pitches_off + pi * 4)
                     if fb_pitches_off is not None else None)
            offset = (_r32(ps_fb_ptr,
                           fb_offsets_off + pi * 4)
                      if fb_offsets_off is not None else None)

            # obj[] is an array of pointers
            gem_obj_ptr = None
            if fb_obj_off is not None:
                gem_obj_ptr = self.ramdump.read_pointer(
                    ps_fb_ptr + fb_obj_off + pi * PTR)

            out.write("        plane[{}]:\n".format(pi))
            out.write("          pitch        : {}\n".format(pitch))
            out.write("          offset       : {}\n".format(offset))
            out.write("          gem_obj ptr  : {}\n".format(
                "0x{:x}".format(gem_obj_ptr)
                if gem_obj_ptr else "NULL"))

            # msm_gem_object: container_of(gem_obj, msm_gem_object, base)
            # base is the first field so msm_gem_obj* == gem_obj*
            if gem_obj_ptr:
                self._dump_gem_object(out, gem_obj_ptr, sde_ps_aspace)

    def _dump_gem_object(self, out, gem_obj_ptr, sde_ps_aspace):
        _foff = self._offset
        _r32 = self._read_u32

        msm_base_off = _foff('struct msm_gem_object', 'base') or 0
        msm_obj_ptr = gem_obj_ptr - msm_base_off

        gem_size_off = _foff('struct drm_gem_object', 'size')
        msm_vaddr_off = _foff('struct msm_gem_object', 'vaddr')
        msm_name_off = _foff('struct msm_gem_object', 'name')
        msm_offset_off = _foff('struct msm_gem_object', 'offset')
        # vmas: list_head of msm_gem_vma entries
        msm_vmas_off = _foff('struct msm_gem_object', 'vmas')
        # msm_gem_vma fields
        vma_list_off = _foff('struct msm_gem_vma', 'list')
        vma_iova_off = _foff('struct msm_gem_vma', 'iova')
        vma_aspace_off = _foff('struct msm_gem_vma', 'aspace')
        vma_mapped_off = _foff('struct msm_gem_vma', 'mapped')
        vma_inuse_off = _foff('struct msm_gem_vma', 'inuse')

        gem_size = (self.ramdump.read_u64(
            gem_obj_ptr + gem_size_off)
            if gem_size_off is not None else None)
        msm_vaddr = (self.ramdump.read_pointer(
            msm_obj_ptr + msm_vaddr_off)
            if msm_vaddr_off is not None else None)
        msm_name = (self.ramdump.read_cstring(
            msm_obj_ptr + msm_name_off, 32)
            if msm_name_off is not None else None)
        msm_offset = (_r32(msm_obj_ptr, msm_offset_off)
                      if msm_offset_off is not None else None)

        out.write("          --- msm_gem_object @ 0x{:x}\n".format(
            msm_obj_ptr))
        out.write("            name         : {}\n".format(
            msm_name or 'N/A'))
        out.write("            size         : {}\n".format(
            "0x{:x} ({} bytes)".format(gem_size, gem_size)
            if gem_size is not None else 'N/A'))
        out.write("            vaddr        : {}\n".format(
            "0x{:x}".format(msm_vaddr)
            if msm_vaddr else 'N/A'))
        out.write("            fb_offset    : {}\n".format(
            msm_offset))

        # Walk msm_gem_object.vmas list to find all
        # mapped IOVAs (one per address space).
        # The IOVA used by the hardware is in the
        # msm_gem_vma whose aspace matches
        # sde_plane_state.aspace.
        self._dump_gem_vmas(out, msm_obj_ptr, msm_offset, sde_ps_aspace, msm_vmas_off, vma_list_off, vma_iova_off, vma_aspace_off, vma_mapped_off, vma_inuse_off)

    def _dump_gem_vmas(self, out, msm_obj_ptr, msm_offset, sde_ps_aspace, msm_vmas_off, vma_list_off, vma_iova_off, vma_aspace_off, vma_mapped_off, vma_inuse_off):
        _r32 = self._read_u32

        if (msm_vmas_off is not None
                and vma_list_off is not None
                and vma_iova_off is not None):
            vmas_head = msm_obj_ptr + msm_vmas_off
            out.write("            vmas (iova per aspace):\n")
            vma_count = 0
            for vma_addr in ListWalker(
                    self.ramdump, vmas_head,
                    vma_list_off):
                vma_iova = self.ramdump.read_u64(
                    vma_addr + vma_iova_off)
                vma_aspace = (self.ramdump.read_pointer(
                    vma_addr + vma_aspace_off)
                    if vma_aspace_off is not None
                    else None)
                vma_mapped = (self.ramdump.read_byte(
                    vma_addr + vma_mapped_off)
                    if vma_mapped_off is not None
                    else None)
                vma_inuse = (_r32(vma_addr, vma_inuse_off)
                             if vma_inuse_off is not None
                             else None)
                # mark the vma whose aspace matches
                # sde_plane_state.aspace
                active_marker = ''
                if (vma_aspace is not None
                        and sde_ps_aspace is not None
                        and vma_aspace == sde_ps_aspace):
                    active_marker = '  <-- active (pstate->aspace)'
                eff_addr = (vma_iova + msm_offset
                            if (vma_iova is not None
                                and msm_offset is not None)
                            else None)
                out.write(
                    "              [vma @ 0x{:x}]"
                    "  aspace={}  iova=0x{:016x}"
                    "  iova+fb_offset={}  mapped={}  inuse={}"
                    "{}\n".format(
                        vma_addr,
                        "0x{:x}".format(vma_aspace)
                        if vma_aspace else "NULL",
                        vma_iova if vma_iova else 0,
                        "0x{:016x}".format(eff_addr)
                        if eff_addr is not None else 'N/A',
                        bool(vma_mapped)
                        if vma_mapped is not None else 'N/A',
                        vma_inuse,
                        active_marker))
                vma_count += 1
                if vma_count > MAX_REPORTED_VMAS:
                    out.write("              (truncated)\n")
                    break
            if vma_count == 0:
                out.write("              (empty — not mapped)\n")
        else:
            out.write("            vmas         : "
                      "(offsets unavailable)\n")

    def _locate_mode_config(self, out):
        _foff = self._offset

        # ------------------------------------------------------------------
        # 1. Locate drm_device via sde_dbg_base (the reliable global symbol)
        #
        # sde_dbg_base  (global struct sde_dbg_base, NOT a pointer)
        #   .dev          -> struct device *  (platform_device.dev)
        #   .driver_data  -> struct drm_device *  (set by platform_set_drvdata)
        #   .dev_private  -> struct msm_drm_private *
        #   .kms          -> struct msm_kms *
        #                    container_of -> struct sde_kms *  (base is first field)
        #   .dev          -> struct drm_device *  (same as above, cross-check)
        # ------------------------------------------------------------------
        sde_dbg_base_sym = self.ramdump.address_of('sde_dbg_base')
        if not sde_dbg_base_sym:
            out.write("ERROR: kernel symbol 'sde_dbg_base' not found.\n")
            print_out_str("dump_commit_state: 'sde_dbg_base' symbol not found")
            out.close()
            return

        # sde_dbg_base is an embedded struct (not a pointer), so its symbol
        # address IS the struct address.
        sde_dbg_base_addr = sde_dbg_base_sym
        out.write("(struct sde_dbg_base)        sde_dbg_base @ 0x{:x}\n".format(
            sde_dbg_base_addr))

        # sde_dbg_base.dev  ->  struct device *  (platform_device.dev)
        dbg_dev_off = _foff('struct sde_dbg_base', 'dev')
        if dbg_dev_off is None:
            out.write("ERROR: cannot resolve sde_dbg_base.dev offset.\n")
            out.close()
            return
        pdev_dev_ptr = self.ramdump.read_pointer(sde_dbg_base_addr + dbg_dev_off)
        if not pdev_dev_ptr:
            out.write("ERROR: sde_dbg_base.dev is NULL.\n")
            out.close()
            return
        out.write("(struct device *)            pdev->dev    @ 0x{:x}\n".format(
            pdev_dev_ptr))

        # device.driver_data  ->  struct drm_device *
        # (set via platform_set_drvdata / dev_set_drvdata)
        drv_data_off = _foff('struct device', 'driver_data')
        if drv_data_off is None:
            out.write("ERROR: cannot resolve device.driver_data offset.\n")
            out.close()
            return
        drm_dev_ptr = self.ramdump.read_pointer(pdev_dev_ptr + drv_data_off)
        if not drm_dev_ptr:
            out.write("ERROR: device->driver_data (drm_device) is NULL.\n")
            out.close()
            return
        out.write("(struct drm_device *)        drm_dev      @ 0x{:x}\n".format(
            drm_dev_ptr))

        # drm_device.dev_private  ->  struct msm_drm_private *
        dev_private_off = _foff('struct drm_device', 'dev_private')
        msm_priv_ptr = (self.ramdump.read_pointer(drm_dev_ptr + dev_private_off)
                        if dev_private_off is not None else None)
        if msm_priv_ptr:
            out.write("(struct msm_drm_private *)   msm_priv     @ 0x{:x}\n".format(
                msm_priv_ptr))

            # msm_drm_private.kms  ->  struct msm_kms *
            # container_of(kms, sde_kms, base): sde_kms.base is first field
            # so sde_kms* == msm_kms*
            kms_off = _foff('struct msm_drm_private', 'kms')
            if kms_off is not None:
                msm_kms_ptr = self.ramdump.read_pointer(msm_priv_ptr + kms_off)
                if msm_kms_ptr:
                    sde_kms_base_off = _foff('struct sde_kms', 'base') or 0
                    sde_kms_ptr = msm_kms_ptr - sde_kms_base_off
                    out.write("(struct sde_kms *)           sde_kms      @ 0x{:x}\n".format(
                        sde_kms_ptr))

        mode_config_off = _foff('struct drm_device', 'mode_config')
        if mode_config_off is None:
            out.write("ERROR: cannot resolve drm_device.mode_config offset.\n")
            out.close()
            return
        mode_config_addr = drm_dev_ptr + mode_config_off
        out.write("(struct drm_mode_config *)   mode_config  @ 0x{:x}\n\n".format(
            mode_config_addr))

        return mode_config_addr

    def parse(self):
        self.dump_commit_state()
