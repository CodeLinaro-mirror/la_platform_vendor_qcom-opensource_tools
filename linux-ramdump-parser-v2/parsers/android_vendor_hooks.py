# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: GPL-2.0-only

from parser_util import register_parser, RamParser

@register_parser('--print-android-vendor-hooks', 'Print android vendor hooks')
class AndroidVH(RamParser):
    def __init__(self, *args):
        super(AndroidVH, self).__init__(*args)

    def get_registered_funcs(self, funcs_addr):
        registered = []
        if not funcs_addr:
            return registered

        size = self.ramdump.sizeof('struct tracepoint_func')

        while True:
            func = self.ramdump.read_structure_field(funcs_addr, 'struct tracepoint_func', 'func')
            if not func:
                break
            func_name = self.ramdump.unwind_lookup(func)[0]
            func_info = self.ramdump.gdbmi.get_func_info(func)
            registered.append((func_name, func_info))
            funcs_addr += size

        return registered

    def dump_tracepoints(self):
        registered_hooks = []
        unregistered_hooks = []

        for line in self.ramdump.lookup_table:
            symbol = line[1]
            if symbol.startswith(('__tracepoint_android_vh', '__tracepoint_android_rvh')):
                sym_addr = self.ramdump.address_of(symbol)
                name_addr = self.ramdump.read_structure_field(sym_addr, 'struct tracepoint', 'name')
                name = self.ramdump.read_cstring(name_addr, 64)

                funcs_addr = self.ramdump.read_structure_field(sym_addr, 'struct tracepoint', 'funcs')
                registered_funcs = self.get_registered_funcs(funcs_addr)
                if not registered_funcs:
                    unregistered_hooks.append(name)
                else:
                    registered_hooks.append((name, registered_funcs))

        with self.ramdump.open_file('android_vendor_hooks.txt') as fout:
            fout.write('--------------------------------------------\n')
            fout.write('Registered Android Vendor Hooks\n')
            fout.write('--------------------------------------------\n')
            fout.write('{:<6} {:<64} {}\n'.format('Index', 'Vendor Hook name', 'Registered Function'))
            for i, (name, registered_funcs) in enumerate(registered_hooks):
                func_name, func_info = registered_funcs[0]
                fout.write(f"{i:<6} {name:<64} {func_name} in {func_info}\n")
                for func_name, func_info in registered_funcs[1:]:
                    fout.write(f"{'':<6} {'':<64} {func_name} in {func_info}\n")

            fout.write('\n')
            fout.write('--------------------------------------------\n')
            fout.write('Unregistered Android Vendor Hooks\n')
            fout.write('--------------------------------------------\n')
            fout.write('{:<6} {:<64}\n'.format('Index', 'Vendor Hook name'))
            for i, name in enumerate(unregistered_hooks):
                fout.write(f'{i:<6} {name:<64}\n')

    def parse(self):
        self.dump_tracepoints()
