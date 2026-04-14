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

from parser_util import register_parser, RamParser, cleanupString, print_out_str
import linux_list as llist


@register_parser('--print-devices', 'Print devices info')
class DevicesList(RamParser):

    def __init__(self, ramdump):
        self.ramdump = ramdump

        # Cache commonly used field offsets
        self.kobj_offset = self.ramdump.field_offset('struct device', 'kobj')
        self.driver_data_offset = self.ramdump.field_offset('struct device', 'driver_data')
        self.dev_bus_offset = self.ramdump.field_offset('struct device', 'bus')
        self.dma_ops_offset = self.ramdump.field_offset('struct device', 'dma_ops')
        self.archdata_offset = self.ramdump.field_offset('struct device', 'archdata')

        self.kobj_entry_offset = self.ramdump.field_offset('struct kobject', 'entry')
        self.kobj_name_offset = self.ramdump.field_offset('struct kobject', 'name')

        self.device_lists = []

    def _read_device_name(self, device):
        """Return the device name from embedded kobject, or None if missing."""
        kobj = self.ramdump.read_word(device + self.kobj_offset)
        if not kobj:
            return None

        name = self.ramdump.read_cstring(kobj + self.kobj_name_offset, 128)
        return cleanupString(name)

    def _read_bus_name(self, device):
        """Return the bus name for a device, or empty string if unavailable."""
        try:
            bus_struct = self.ramdump.read_word(device + self.dev_bus_offset)
            if not bus_struct:
                return ''
            bus_name_ptr = self.ramdump.read_word(bus_struct)
            if not bus_name_ptr:
                return ''
            name = self.ramdump.read_cstring(bus_name_ptr, 128)
            return name or ''
        except Exception:
            return ''

    def _read_cma_info(self, device):
        """Return (cma_area, cma_name) for a device."""
        cma_area = self.ramdump.read_structure_field(device, 'struct device', 'cma_area')
        cma_name = ''
        if cma_area:
            try:
                name_off = self.ramdump.field_offset('struct cma', 'name')
                cma_name = self.ramdump.read_cstring(cma_area + name_off, 48) or ''
            except Exception:
                # Ignore any issues reading CMA name; keep defaults
                cma_name = ''
        return cma_area, cma_name

    def _read_dma_ops_name(self, device):
        """Return a short string for dma_ops symbol name, e.g. '[dma_direct_ops]'."""
        dma_ops = self.ramdump.read_structure_field(device, 'struct device', 'dma_ops')
        if not dma_ops:
            return '[]'
        a_ops_name = self.ramdump.unwind_lookup(dma_ops)
        if not a_ops_name:
            return '[]'
        dma_ops_name, _addr = a_ops_name
        return f'[{dma_ops_name}]'

    def list_func(self, device, fout):
        """Callback used by the list walker for each device."""
        dev_name = self._read_device_name(device)
        if not dev_name:
            dev_name = "unknown"

        driver_data = self.ramdump.read_word(device + self.driver_data_offset)
        bus_name = self._read_bus_name(device)
        cma_area, cma_name = self._read_cma_info(device)
        dma_ops_str = self._read_dma_ops_name(device)
        archdata = device + self.archdata_offset

        try:
            if fout is not None:
                ROW_FMT = "%#18x %-64s %-16s %#18x %#18x %-20s %s\n"
                fout.write(
                    ROW_FMT
                    % (
                        device,              # pointer to struct device
                        dev_name,            # device name string
                        bus_name or "",      # bus->name or ""
                        driver_data,         # driver_data pointer
                        cma_area,            # cma pointer
                        cma_name or "",      # cma name string
                        dma_ops_str,         # e.g. "[]" or some description
                    )
                )
        except Exception as e:
            # Use common parser print utility
            print_out_str(f"Error printing device 0x{device:x}: {e}")

        # Save a compact representation of the device
        self.device_lists.append([device, dev_name, bus_name, driver_data, archdata])

    def get_device_list(self, fout=None):
        """
        Walk devices_kset and collect devices.
        Returns a list of [device_addr, name, bus_name, driver_data, archdata_addr].
        """
        devices_kset = self.ramdump.read_pointer('devices_kset')
        if not devices_kset:
            print_out_str("devices_kset is NULL or cannot be read")
            return self.device_lists

        list_head = devices_kset + self.ramdump.field_offset('struct kset', 'list')
        list_offset = self.kobj_offset + self.kobj_entry_offset

        list_walker = llist.ListWalker(self.ramdump, list_head, list_offset)
        list_walker.walk(self.list_func, fout)

        return self.device_lists

    def parse(self):
        fout = self.ramdump.open_file('devices.txt')
        try:
            # header
            header = "%-18s %-40s %-16s %-18s %-18s  %-18s %s\n" % (
                "addr", "name", "bus_name", "driver_data", "v.v (struct cma)", "cma_name",  "dma_ops"
            )
            fout.write(header)
            self.get_device_list(fout)
        finally:
            fout.close()
