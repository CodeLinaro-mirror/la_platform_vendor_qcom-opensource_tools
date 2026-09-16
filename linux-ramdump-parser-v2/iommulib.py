# Copyright (c) 2014-2020, The Linux Foundation. All rights reserved.
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

import rb_tree
import math
import re
import linux_list as llist
from mm import phys_to_virt
from print_out import print_out_str
from dpd_proxy_iommulib import _collect_mappings as _dpd_collect_mappings

ARM_SMMU_DOMAIN = 0
MSM_SMMU_DOMAIN = 1
MSM_SMMU_AARCH64_DOMAIN = 2
DPD_SMMU_DOMAIN = 3
ARM_LPAE_MAX_LEVELS=4

class Domain(object):
    def __init__(self, pg_table, redirect, ctx_list, client_name,
                 domain_type=MSM_SMMU_DOMAIN, level=3, domain_num=-1):
        self.domain_num = domain_num
        self.pg_table = pg_table
        self.redirect = redirect
        self.ctx_list = ctx_list
        self.client_name = client_name
        self.level = level
        self.domain_type = domain_type

    def __repr__(self):
        return "#%d: %s" % (self.domain_num, self.client_name)


class DpdSmmuDomain(Domain):
        def __init__(self, domain_ptr, smmu_domain_ptr, client_name,
                 si_domain_id, attached):
           super(DpdSmmuDomain, self).__init__(
               pg_table=0, redirect=0, ctx_list=[],
               client_name=client_name, domain_type=DPD_SMMU_DOMAIN)
           self.domain_ptr      = domain_ptr
           self.smmu_domain_ptr = smmu_domain_ptr
           self.si_domain_id    = si_domain_id
           self.attached        = attached
           self.mappings        = []


class IommuLib(object):
    def __init__(self, ramdump):
        self.ramdump = ramdump
        self.domain_list = []
        self.arm_smmu_v12 = False

        try:
            if self.find_iommu_domains_msm_iommu():
                pass
            if self.find_iommu_domains_debug_attachments():
                pass
            if self.find_iommu_domains_device_core():
                pass
        except:
            if self.ramdump.arm_smmu_v12:
                self.arm_smmu_v12 = True
                self.find_iommu_domains_device_core()

        self._find_dpd_proxy_domains()

    """
    legacy code - pre-8996/kernel 4.4?
    """
    def find_iommu_domains_msm_iommu(self):
        domains = list()
        root = self.ramdump.read_word('domain_root')
        if root is None:
            return False

        rb_walker = rb_tree.RbTreeWalker(self.ramdump)
        rb_walker.walk(root, self._iommu_domain_func, self.domain_list)
        return True

    def use_only_iommu_debug_attachments(self, debug_attachment):
        has_pgtbl_info = self.ramdump.read_structure_field(debug_attachment,
                         'struct iommu_debug_attachment', 'fmt')
        has_client_name = self.ramdump.read_structure_field(debug_attachment,
                         'struct iommu_debug_attachment', 'client_name')

        if has_pgtbl_info and has_client_name:
            return True;
        return False

    def find_iommu_domains_legacy(self, debug_attachment):
        domain_ptr = self.ramdump.read_structure_field( debug_attachment,
                     'struct iommu_debug_attachment', 'domain')

        if not domain_ptr:
            return

        ptr = self.ramdump.read_structure_field(
            debug_attachment, 'struct iommu_debug_attachment', 'group')
        if ptr is not None:
            dev_list = ptr + self.ramdump.field_offset(
                'struct iommu_group', 'devices')
            dev = self.ramdump.read_structure_field(
                dev_list, 'struct list_head', 'next')
            if self.ramdump.kernel_version >= (4, 14):
                client_name = self.ramdump.read_structure_cstring(
                    dev, 'struct group_device', 'name')
            else:
                client_name = self.ramdump.read_structure_cstring(
                    dev, 'struct iommu_device', 'name')
        else:
            """Older kernel versions have the field 'dev'
            instead of 'iommu_group'.
            """
            ptr = self.ramdump.read_structure_field(
                debug_attachment, 'struct iommu_debug_attachment', 'dev')
            kobj_ptr = ptr + self.ramdump.field_offset('struct device', 'kobj')
            client_name = self.ramdump.read_structure_cstring(
                kobj_ptr, 'struct kobject', 'name')


        has_pgtbl_info = self.ramdump.read_structure_field(debug_attachment,\
                         'struct iommu_debug_attachment', 'fmt') is not None
        if self.ramdump.kernel_version >= (5, 4, 0) and has_pgtbl_info:
            self._find_iommu_domains_debug_attachments(debug_attachment,\
                                            client_name, self.domain_list)
        else:
            # Pass iommu_ops=None, group_ptr=None for legacy path (no device walk)
            self._find_iommu_domains_arm_smmu(domain_ptr, client_name,\
                                              self.domain_list, None, None)

    def find_iommu_domains(self, debug_attachment):
        client_name = self.ramdump.read_structure_cstring(debug_attachment,
                      'struct iommu_debug_attachment', 'client_name')
        self._find_iommu_domains_debug_attachments(debug_attachment,
                                                   client_name,
                                                   self.domain_list)

    """
    depends on CONFIG_IOMMU_DEBUG_TRACKING
    """
    def find_iommu_domains_debug_attachments(self):
        list_head_attachments = self.ramdump.address_of(
                                                    'iommu_debug_attachments')
        if list_head_attachments is None:
            return False

        offset = self.ramdump.field_offset('struct iommu_debug_attachment',
                                          'list')
        list_walker = llist.ListWalker(self.ramdump, list_head_attachments, offset)

        for debug_attachment in list_walker:
            if self.use_only_iommu_debug_attachments(debug_attachment):
                self.find_iommu_domains(debug_attachment)
            else:
                self.find_iommu_domains_legacy(debug_attachment)

        return True

    """
    will generate domains using only the information stored in the debug
    attachments structure.
    """
    def _find_iommu_domains_debug_attachments(self, debug_attachment,\
                                              client_name, domain_list):
        levels = self.ramdump.read_structure_field(debug_attachment,\
                                    'struct iommu_debug_attachment', 'levels')
        pg_table = self.ramdump.read_structure_field(debug_attachment,\
                                'struct iommu_debug_attachment', 'ttbr0')
        domain = Domain(pg_table, 0, [], client_name, ARM_SMMU_DOMAIN,
                        levels)
        domain_list.append(domain)

    """
    will only find active iommu domains. This means it will exclude most gpu domains.
    """
    def find_iommu_domains_device_core(self):
        domains = set()
        devices_kset = self.ramdump.read_pointer('devices_kset')
        if not devices_kset:
            return False

        list_head = devices_kset + self.ramdump.field_offset('struct kset',
                                                             'list')

        offset = self.ramdump.field_offset('struct device', 'kobj.entry')
        list_walker = llist.ListWalker(self.ramdump, list_head, offset)

        # Resolve arm_smmu_ops for SMMUv3 (arm-smmu-v3.c) once, used below
        arm_smmu_v3_ops = None
        try:
            arm_smmu_v3_ops = self.ramdump.address_of_symbol_from_file(
                'arm_smmu_ops', 'arm-smmu-v3.c')
        except Exception:
            pass

        for dev in list_walker:
            iommu_group = self.ramdump.read_structure_field(dev, 'struct device', 'iommu_group')
            if not iommu_group:
                continue

            domain_ptr = self.ramdump.read_structure_field(iommu_group, 'struct iommu_group', 'domain')
            if not domain_ptr:
                continue

            if domain_ptr in domains:
                continue

            domains.add(domain_ptr)

            client_name_addr = self.ramdump.read_structure_field(dev, 'struct device', 'kobj.name')
            client_name = self.ramdump.read_cstring(client_name_addr)

            """
            Skip KGSL SID0 client as GPU per-process pagetable feature has many
            pagetables associated with a device. Extracting these is not currently supported
            """
            if re.match("[0-9]+\.vfio_kgsl", client_name) :
                continue

            iommu_ptr = self.ramdump.read_structure_field(dev, 'struct device', 'iommu')
            iommu_dev = self.ramdump.read_structure_field(iommu_ptr, 'struct dev_iommu', 'iommu_dev')
            iommu_ops = self.ramdump.read_structure_field(iommu_dev, 'struct iommu_device', 'ops')

            if self.arm_smmu_v12:
                self._find_iommu_domains_arm_smmu_v12(domain_ptr, client_name, self.domain_list)
            elif arm_smmu_v3_ops is not None and iommu_ops == arm_smmu_v3_ops:
                # SMMUv3 device — use the v3-specific extractor
                self._find_iommu_domains_arm_smmu_v3(domain_ptr, client_name, self.domain_list)
            else:
                self._find_iommu_domains_arm_smmu(domain_ptr, client_name, self.domain_list, iommu_ops, iommu_group)

        return True

    def _find_iommu_domains_arm_smmu_v3(self, domain_ptr, client_name, domain_list):
        """
        Extract the S1 page table base and translation level count for an
        ARM SMMUv3 domain (upstream arm-smmu-v3.c driver).

        Data structure path:
          iommu_domain (domain_ptr)
            → container_of → struct arm_smmu_domain   [arm-smmu-v3.h]
              → pgtbl_ops  (struct io_pgtable_ops *)
                → container_of → struct arm_lpae_io_pgtable
                  → iop.cfg.arm_lpae_s1_cfg.ttbr   (physical address of L0/L1 PT)
                  → start_level                     (0=4-level, 1=3-level, ...)
        """
        ramdump = self.ramdump

        # Switch GDB namespace to arm-smmu-v3.h so that 'struct arm_smmu_domain'
        # resolves to the v3 definition (not the v2 one from arm-smmu.h).
        ramdump.set_priority_namespace('arm-smmu-v3.h')

        try:
            arm_smmu_domain_ptr = ramdump.container_of(
                domain_ptr, 'struct arm_smmu_domain', 'domain')
            if arm_smmu_domain_ptr is None:
                return

            pgtbl_ops_ptr = ramdump.read_structure_field(
                arm_smmu_domain_ptr, 'struct arm_smmu_domain', 'pgtbl_ops')
            if not pgtbl_ops_ptr:
                return

            arm_lpae_io_pgtable_ptr = ramdump.container_of(
                pgtbl_ops_ptr, 'struct arm_lpae_io_pgtable', 'iop.ops')
            if arm_lpae_io_pgtable_ptr is None:
                return

            # Prefer start_level (upstream kernel >= 5.15) over levels
            start_level = ramdump.read_structure_field(
                arm_lpae_io_pgtable_ptr, 'struct arm_lpae_io_pgtable', 'start_level')
            if start_level is not None:
                level = ARM_LPAE_MAX_LEVELS - start_level
            else:
                level = ramdump.read_structure_field(
                    arm_lpae_io_pgtable_ptr, 'struct arm_lpae_io_pgtable', 'levels')
                if level is None:
                    level = 3  # safe default for 39-bit VA (3-level LPAE)

            # Read TTBR0 from io_pgtable cfg
            pg_table = ramdump.read_structure_field(
                arm_lpae_io_pgtable_ptr, 'struct arm_lpae_io_pgtable',
                'iop.cfg.arm_lpae_s1_cfg.ttbr')

            if pg_table is None or pg_table == 0:
                # Fallback: read from arm_smmu_domain.s1_cfg.cd.ttbr
                # (field layout: arm_smmu_domain → s1_cfg → cd → ttbr)
                pg_table = ramdump.read_structure_field(
                    arm_smmu_domain_ptr, 'struct arm_smmu_domain',
                    's1_cfg.cd.ttbr')

            if pg_table is None or pg_table == 0:
                return

            # Mask to 48-bit physical address (bits 47:0)
            pg_table = pg_table & 0xffffffffffff

            pg_table_virt = phys_to_virt(ramdump, pg_table)

            domain_create = Domain(pg_table_virt, 0, [], client_name,
                                   ARM_SMMU_DOMAIN, level)
            domain_list.append(domain_create)

        except Exception as e:
            print_out_str("[iommulib] _find_iommu_domains_arm_smmu_v3 failed "
                          "for '%s': %s" % (client_name, str(e)))
    
    def _find_dpd_proxy_domains(self):
        """
        Walk the global device list and append a DpdSmmuDomain to
        self.domain_list for every device whose IOMMU is the DPD proxy driver.

        This method is called unconditionally from __init__() so that DPD proxy
        domains are found regardless of which of the three primary discovery
        paths (msm_iommu / debug_attachments / device_core) was taken.
        """
        dpd_smmu_driver_addr = self.ramdump.address_of('dpd_smmu_driver')
        if dpd_smmu_driver_addr is None:
            return

        driver_offset = self.ramdump.field_offset(
            'struct platform_driver', 'driver')
        if driver_offset is None:
            return
        dpd_driver_addr = dpd_smmu_driver_addr + driver_offset

        devices_kset = self.ramdump.read_pointer('devices_kset')
        if not devices_kset:
            return

        list_head = devices_kset + self.ramdump.field_offset('struct kset', 'list')
        dev_entry_offset = self.ramdump.field_offset('struct device', 'kobj.entry')
        list_walker = llist.ListWalker(self.ramdump, list_head, dev_entry_offset)

        seen_domains = set()

        for dev in list_walker:
            try:
                iommu_group = self.ramdump.read_structure_field(
                    dev, 'struct device', 'iommu_group')
                if not iommu_group:
                    continue

                domain_ptr = self.ramdump.read_structure_field(
                    iommu_group, 'struct iommu_group', 'domain')
                if not domain_ptr:
                    continue

                if domain_ptr in seen_domains:
                    continue

                iommu_ptr = self.ramdump.read_structure_field(
                    dev, 'struct device', 'iommu')
                if not iommu_ptr:
                    continue

                iommu_dev = self.ramdump.read_structure_field(
                    iommu_ptr, 'struct dev_iommu', 'iommu_dev')
                if not iommu_dev:
                    continue

                iommu_dev_dev = self.ramdump.read_structure_field(
                    iommu_dev, 'struct iommu_device', 'dev')
                if not iommu_dev_dev:
                    continue

                parent_dev = self.ramdump.read_structure_field(
                    iommu_dev_dev, 'struct device', 'parent')
                if not parent_dev:
                    continue

                parent_driver = self.ramdump.read_structure_field(
                    parent_dev, 'struct device', 'driver')

                if parent_driver != dpd_driver_addr:
                    continue

                seen_domains.add(domain_ptr)

                kobj_name_ptr = self.ramdump.read_structure_field(
                    dev, 'struct device', 'kobj.name')
                client_name = (self.ramdump.read_cstring(kobj_name_ptr)
                               if kobj_name_ptr else 'unknown') or 'unknown'

                self._find_iommu_domains_dpd_proxy(
                    domain_ptr, client_name, self.domain_list)

            except Exception as e:
                print_out_str(
                    "DPD proxy IOMMU: exception processing device "
                    "0x%x: %s" % (dev, e))
                continue

    def _find_iommu_domains_dpd_proxy(self, domain_ptr, client_name, domain_list):
        domain_field_offset = self.ramdump.field_offset(
            'struct dpd_smmu_domain', 'domain')
        if domain_field_offset is None:
            print_out_str(
                "DPD proxy IOMMU: 'struct dpd_smmu_domain' not found in "
                "debug info. Ensure the module was built with debug symbols.")
            return

        smmu_domain_ptr = domain_ptr - domain_field_offset

        si_domain_id = self.ramdump.read_structure_field(
            smmu_domain_ptr, 'struct dpd_smmu_domain', 'si_domain_id')
        attached = self.ramdump.read_structure_field(
            smmu_domain_ptr, 'struct dpd_smmu_domain', 'attached')

        domain = DpdSmmuDomain(
            domain_ptr      = domain_ptr,
            smmu_domain_ptr = smmu_domain_ptr,
            client_name     = client_name,
            si_domain_id    = si_domain_id,
            attached        = bool(attached) if attached is not None else False,
        )

        _dpd_collect_mappings(self.ramdump, domain, smmu_domain_ptr)

        domain_list.append(domain)

    def _find_iommu_domains_arm_smmu_v12(self, domain_ptr, client_name, domain_list):
        if self.ramdump.field_offset('struct iommu_domain', 'priv') \
                is not None:
            priv_ptr = self.ramdump.read_structure_field(
                domain_ptr, 'struct iommu_domain', 'priv')

            if not priv_ptr:
                return
        else:
            priv_ptr = None

        arm_smmu_ops_data = self.ramdump.address_of('arm_smmu_ops')
        smmu_iommu_ops_offset = self.ramdump.field_offset('struct iommu_ops','default_domain_ops')
        arm_smmu_ops = arm_smmu_ops_data + smmu_iommu_ops_offset

        iommu_domain_ops = self.ramdump.read_structure_field(
            domain_ptr, 'struct iommu_domain', 'ops')
        if iommu_domain_ops is None or iommu_domain_ops == 0:
            return


        if priv_ptr is not None:
            arm_smmu_domain_ptr = priv_ptr
        else:
            arm_smmu_domain_offset = 0x88 #0x60
            arm_smmu_domain_ptr = domain_ptr - arm_smmu_domain_offset

        pgtbl_ops_ptr =  self.ramdump.read_u64(arm_smmu_domain_ptr + 0x8)

        if pgtbl_ops_ptr is None or pgtbl_ops_ptr == 0:
            return

        level = 0
        fn = self.ramdump.read_structure_field(pgtbl_ops_ptr,
                'struct io_pgtable_ops', 'map')
        if fn == self.ramdump.address_of('av8l_fast_map'):
            level = 3
        else:
            arm_lpae_io_pgtable_ptr = self.ramdump.container_of(
                pgtbl_ops_ptr, 'struct arm_lpae_io_pgtable', 'iop.ops')

            level = self.ramdump.read_structure_field(
                arm_lpae_io_pgtable_ptr, 'struct arm_lpae_io_pgtable',
                'levels')


        io_pgtable_ptr = self.ramdump.container_of(pgtbl_ops_ptr , 'struct io_pgtable', 'ops')
        pg_table = self.ramdump.read_structure_field(io_pgtable_ptr, 'struct io_pgtable','cfg.arm_lpae_s1_cfg.ttbr')

        pg_table = phys_to_virt(self.ramdump, pg_table)

        domain_create = Domain(pg_table, 0, [], client_name,
                               ARM_SMMU_DOMAIN, level)
        domain_list.append(domain_create)

    def _find_iommu_domains_arm_smmu(self, domain_ptr, client_name, domain_list, iommu_ops, group_ptr):
        """
        Extract S1 page table info for an ARM SMMUv2 domain.

        Must be called with the GDB namespace set to arm-smmu.h (SMMUv2) so
        that 'struct arm_smmu_domain' resolves to the v2 definition.
        This is critical in mixed SMMUv2+v3 systems where both drivers are
        loaded simultaneously and both define 'struct arm_smmu_domain' with
        different layouts.
        """
        ramdump = self.ramdump

        # Explicitly set arm-smmu.h (SMMUv2) as the priority namespace.
        # This MUST be done before any struct field access to ensure correct
        # offsets when both SMMUv2 and SMMUv3 drivers are loaded together.
        ramdump.set_priority_namespace('arm-smmu.h')

        if self.ramdump.field_offset('struct iommu_domain', 'priv') \
                is not None:
            priv_ptr = self.ramdump.read_structure_field(
                domain_ptr, 'struct iommu_domain', 'priv')

            if not priv_ptr:
                return
        else:
            priv_ptr = None

        if self.ramdump.kernel_version >= (5, 4, 0):
            smmu_iommu_ops_offset = self.ramdump.field_offset('struct msm_iommu_ops','iommu_ops')
            if smmu_iommu_ops_offset is not None:
                arm_smmu_ops_data = self.ramdump.address_of('arm_smmu_ops')
                arm_smmu_ops = arm_smmu_ops_data + smmu_iommu_ops_offset
            else:
                """ Required to specify driver in case both SMMUv2 and SMMUv3 driver are enabled """
                arm_smmu_ops = self.ramdump.address_of_symbol_from_file('arm_smmu_ops', 'arm-smmu.c')
        else:
            arm_smmu_ops = self.ramdump.address_of('arm_smmu_ops')

        iommu_domain_ops = self.ramdump.read_structure_field(
            domain_ptr, 'struct iommu_domain', 'ops')
        if iommu_domain_ops is None or iommu_domain_ops == 0:
            return

        if iommu_domain_ops == arm_smmu_ops or iommu_ops == arm_smmu_ops:
            if priv_ptr is not None:
                arm_smmu_domain_ptr = priv_ptr
            elif self.ramdump.kernel_version >= (5, 4, 0):
                arm_smmu_domain_ptr_wrapper = self.ramdump.container_of(
                        domain_ptr, 'struct msm_iommu_domain', 'iommu_domain')
                if arm_smmu_domain_ptr_wrapper is not None:
                    arm_smmu_domain_ptr = self.ramdump.container_of(
                        arm_smmu_domain_ptr_wrapper, 'struct arm_smmu_domain', 'domain')
                else:
                    self.ramdump.set_priority_namespace('arm-smmu.h')
                    arm_smmu_domain_ptr = self.ramdump.container_of(
                        domain_ptr, 'struct arm_smmu_domain', 'domain')
            else:
                arm_smmu_domain_ptr = self.ramdump.container_of(
                    domain_ptr, 'struct arm_smmu_domain', 'domain')
            pgtbl_ops_ptr = self.ramdump.read_structure_field(
                arm_smmu_domain_ptr, 'struct arm_smmu_domain', 'pgtbl_ops')
            if pgtbl_ops_ptr is None or pgtbl_ops_ptr == 0:
                return

            level = 0
            fn = self.ramdump.read_structure_field(pgtbl_ops_ptr,
                    'struct io_pgtable_ops', 'map')
            if fn == self.ramdump.address_of('av8l_fast_map'):
                level = 3
            else:
                arm_lpae_io_pgtable_ptr = self.ramdump.container_of(
                    pgtbl_ops_ptr, 'struct arm_lpae_io_pgtable', 'iop.ops')

                level = self.ramdump.read_structure_field(
                    arm_lpae_io_pgtable_ptr, 'struct arm_lpae_io_pgtable',
                    'levels')

            if self.ramdump.kernel_version >= (5, 4, 0):
                pgtbl_info_offset = self.ramdump.field_offset('struct arm_smmu_domain','pgtbl_info')
                if pgtbl_info_offset is not None:
                    pgtbl_info_data = arm_smmu_domain_ptr + pgtbl_info_offset
                    pg_table = self.ramdump.read_structure_field(pgtbl_info_data,'struct msm_io_pgtable_info','pgtbl_cfg.arm_lpae_s1_cfg.ttbr[0]')
                else:
                    """ Set arm-smmu-v2 as priority for symbol identification """
                    """ Required in case both SMMUv2 and SMMUv3 driver are enabled together """
                    self.ramdump.set_priority_namespace('arm-smmu.h')
                    arm_smmu_cfg_offset = self.ramdump.field_offset('struct arm_smmu_domain','cfg')
                    arm_smmu_ptr = self.ramdump.read_structure_field(arm_smmu_domain_ptr, 'struct arm_smmu_domain', 'smmu')
                    cbs = self.ramdump.read_structure_field(arm_smmu_ptr, 'struct arm_smmu_device', 'cbs')
                    arm_smmu_cfg_ptr = arm_smmu_domain_ptr + arm_smmu_cfg_offset
                    cbndx = self.ramdump.read_structure_field(arm_smmu_cfg_ptr, 'struct arm_smmu_cfg', 'cbndx')
                    cb_offset = cbndx * self.ramdump.sizeof('struct arm_smmu_cb')
                    cb = cbs + cb_offset
                    pg_table =  self.ramdump.read_structure_field(cb, 'struct arm_smmu_cb', 'ttbr[0]')
                    mask = 0xffffffffffff
                    pg_table = pg_table & mask
                    arm_lpae_io_pgtable_ptr = self.ramdump.container_of(
                        pgtbl_ops_ptr, 'struct arm_lpae_io_pgtable', 'iop.ops')
                    start_level = self.ramdump.read_structure_field(
                         arm_lpae_io_pgtable_ptr, 'struct arm_lpae_io_pgtable', 'start_level')
                    level = ARM_LPAE_MAX_LEVELS - start_level

            pg_table = phys_to_virt(self.ramdump, pg_table)

            domain_create = Domain(pg_table, 0, [], client_name,
                                   ARM_SMMU_DOMAIN, level)
            domain_list.append(domain_create)
        else:
            priv_pt_offset = self.ramdump.field_offset('struct msm_iommu_priv',
                                                       'pt')
            pgtable_offset = self.ramdump.field_offset('struct msm_iommu_pt',
                                                       'fl_table')
            redirect_offset = self.ramdump.field_offset('struct msm_iommu_pt',
                                                        'redirect')

            if priv_pt_offset is not None:
                pg_table = self.ramdump.read_u64(
                    priv_ptr + priv_pt_offset + pgtable_offset)
                redirect = self.ramdump.read_u64(
                   priv_ptr + priv_pt_offset + redirect_offset)

            if (self.ramdump.is_config_defined('CONFIG_IOMMU_AARCH64')):
                domain_create = Domain(pg_table, redirect, [], client_name,
                                       MSM_SMMU_AARCH64_DOMAIN)
            else:
                domain_create = Domain(pg_table, redirect, [], client_name,
                                       MSM_SMMU_DOMAIN)

            domain_list.append(domain_create)

    def _iommu_list_func(self, node, ctx_list):
        ctx_drvdata_name_ptr = self.ramdump.read_word(
            node + self.ramdump.field_offset('struct msm_iommu_ctx_drvdata',
                                             'name'))
        ctxdrvdata_num_offset = self.ramdump.field_offset(
            'struct msm_iommu_ctx_drvdata', 'num')
        num = self.ramdump.read_u32(node + ctxdrvdata_num_offset)
        if ctx_drvdata_name_ptr != 0:
            name = self.ramdump.read_cstring(ctx_drvdata_name_ptr, 100)
            ctx_list.append((num, name))

    def _iommu_domain_func(self, node, domain_list):
        domain_num = self.ramdump.read_u32(self.ramdump.sibling_field_addr(
            node, 'struct msm_iova_data', 'node', 'domain_num'))
        domain = self.ramdump.read_word(self.ramdump.sibling_field_addr(
            node, 'struct msm_iova_data', 'node', 'domain'))
        priv_ptr = self.ramdump.read_word(
            domain + self.ramdump.field_offset('struct iommu_domain', 'priv'))

        client_name_offset = self.ramdump.field_offset(
            'struct msm_iommu_priv', 'client_name')

        if client_name_offset is not None:
            client_name_ptr = self.ramdump.read_word(
                priv_ptr + self.ramdump.field_offset(
                    'struct msm_iommu_priv', 'client_name'))
            if client_name_ptr != 0:
                client_name = self.ramdump.read_cstring(client_name_ptr, 100)
            else:
                client_name = '(null)'
        else:
            client_name = 'unknown'

        list_attached_offset = self.ramdump.field_offset(
                'struct msm_iommu_priv', 'list_attached')

        if list_attached_offset is not None:
            list_attached = priv_ptr + list_attached_offset
        else:
            list_attached = None

        priv_pt_offset = self.ramdump.field_offset('struct msm_iommu_priv',
                                                   'pt')
        pgtable_offset = self.ramdump.field_offset('struct msm_iommu_pt',
                                                   'fl_table')
        redirect_offset = self.ramdump.field_offset('struct msm_iommu_pt',
                                                    'redirect')

        if priv_pt_offset is not None:
            pg_table = self.ramdump.read_word(
                priv_ptr + priv_pt_offset + pgtable_offset)
            redirect = self.ramdump.read_u32(
                priv_ptr + priv_pt_offset + redirect_offset)
        else:
            # On some builds we are unable to look up the offsets so hardcode
            # the offsets.
            pg_table = self.ramdump.read_word(priv_ptr + 0)
            redirect = self.ramdump.read_u32(priv_ptr +
                                             self.ramdump.sizeof('void *'))

            # Note: On some code bases we don't have this pg_table and redirect
            # in the priv structure (see msm_iommu_sec.c). It only contains
            # list_attached. If this is the case we can detect that by checking
            # whether pg_table == redirect (prev == next pointers of the
            # attached list).
            if pg_table == redirect:
                # This is a secure domain. We don't have access to the page
                # tables.
                pg_table = 0
                redirect = None

        ctx_list = []
        if list_attached is not None and list_attached != 0:
            list_walker = llist.ListWalker(
                self.ramdump, list_attached,
                self.ramdump.field_offset('struct msm_iommu_ctx_drvdata',
                                          'attached_elm'))
            list_walker.walk(self._iommu_list_func, ctx_list)

            if (self.ramdump.is_config_defined('CONFIG_IOMMU_AARCH64')):
                domain_create = Domain(pg_table, redirect, ctx_list, client_name,
                                       MSM_SMMU_AARCH64_DOMAIN, domain_num=domain_num)
            else:
                domain_create = Domain(pg_table, redirect, ctx_list, client_name,
                                       MSM_SMMU_DOMAIN, domain_num=domain_num)

            domain_list.append(domain_create)
