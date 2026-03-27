# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: GPL-2.0-only

import os
import print_out
from parser_util import RamParser, cleanupString, register_parser
import module_table

@register_parser('--modules_table', 'Dump modules_table')
class Modules_table(RamParser):
    def retrieve_modules_cn(self):
        mem_type_names = {
            0: "MOD_TEXT",
            1: "MOD_DATA",
            2: "MOD_RODATA",
            3: "MOD_RO_AFTER_INIT",
            4: "MOD_INIT_TEXT",
            5: "MOD_INIT_DATA",
            6: "MOD_INIT_RODATA",
        }

        mod_list = self.ramdump.address_of('modules')
        next_offset = self.ramdump.field_offset('struct list_head', 'next')
        list_offset = self.ramdump.field_offset('struct module', 'list')
        name_offset = self.ramdump.field_offset('struct module', 'name')
        state_offset = self.ramdump.field_offset('struct module', 'state')
        scmversion_offset = self.ramdump.field_offset('struct module', 'scmversion')
        init_offset = self.ramdump.field_offset('struct module', 'init')

        mem_base_offsets = []
        mem_size_offsets = []
        MOD_MEM_NUM_TYPES = self.ramdump.gdbmi.get_value_of('MOD_MEM_NUM_TYPES')
        if self.ramdump.kernel_version >= (6, 4, 0):
            for i in range(MOD_MEM_NUM_TYPES):
                try:
                    mem_base_offsets.append(self.ramdump.field_offset('struct module', f'mem[{i}].base'))
                    mem_size_offsets.append(self.ramdump.field_offset('struct module', f'mem[{i}].size'))
                except Exception:
                    break

            module_core_offset = mem_base_offsets[0] if mem_base_offsets else self.ramdump.field_offset(
                'struct module', 'mem[0].base'
            )
        elif self.ramdump.kernel_version > (4, 9, 0):
            module_core_offset = self.ramdump.field_offset('struct module', 'core_layout.base')
        else:
            module_core_offset = self.ramdump.field_offset('struct module', 'module_core')

        kallsyms_offset = self.ramdump.field_offset('struct module', 'kallsyms')
        next_list_ent = self.ramdump.read_pointer(mod_list + next_offset)

        while next_list_ent and next_list_ent != mod_list:
            mod_tbl_ent = module_table.module_table_entry()
            module = next_list_ent - list_offset
            name_ptr = module + name_offset

            init_addr = self.ramdump.read_pointer(module + init_offset) or 0
            init_name = "unknown"
            if init_addr:
                wname = self.ramdump.unwind_lookup(init_addr)
                if wname is not None:
                    init_name, _off = wname

            mod_tbl_ent.name = self.ramdump.read_cstring(name_ptr)
            state = self.ramdump.read_u32(state_offset + module)

            svmversion_addr = self.ramdump.read_pointer(scmversion_offset + module)
            svmversion = ""
            if svmversion_addr:
                svmversion = self.ramdump.read_cstring(svmversion_addr)

            mod_tbl_ent.module_offset = self.ramdump.read_pointer(module + module_core_offset) or 0
            mod_tbl_ent.kallsyms_addr = self.ramdump.read_pointer(module + kallsyms_offset)

            # Compute module start/end
            mod_start = 0
            mod_end = 0
            if self.ramdump.kernel_version >= (6, 4, 0) and mem_base_offsets:
                for boff, soff in zip(mem_base_offsets, mem_size_offsets):
                    base = self.ramdump.read_pointer(module + boff) or 0
                    size = self.ramdump.read_u32(module + soff) or 0
                    if not base or not size:
                        continue
                    end = base + size
                    if mod_start == 0 or base < mod_start:
                        mod_start = base
                    if end > mod_end:
                        mod_end = end
            else:
                # Best-effort for older layouts: treat core base as module span start.
                mod_start = mod_tbl_ent.module_offset
                mod_end = 0

            self.module_table_cn.add_entry(mod_tbl_ent)

             # Collect mem[] regions for printing
            mem_regions = []
            if self.ramdump.kernel_version >= (6, 4, 0) and mem_base_offsets:
                for i, (boff, soff) in enumerate(zip(mem_base_offsets, mem_size_offsets)):
                    base = self.ramdump.read_pointer(module + boff) or 0
                    size = self.ramdump.read_u32(module + soff) or 0
                    if base and size:
                        mem_regions.append((i, base, size))
            self.modules_list.append(
                (mod_tbl_ent.module_offset, mod_tbl_ent.name, module, svmversion, state,
                 init_addr, init_name, mem_regions)
            )
            next_list_ent = self.ramdump.read_pointer(next_list_ent + next_offset)

        self.modules_list.sort()
        for item in self.modules_list:
            core_base, name, module_addr, scmver, state, init_addr, init_name, mem_regions = item
            print(
                "%-32s 0x%-16x (struct module)0x%-16x %-16s state %8d init 0x%-16x %-30s"
                % (name, core_base, module_addr, scmver, state, init_addr, init_name),
                file=self.f,
            )

            # NEW: print each mem[] line indented under the module
            for idx, base, size in mem_regions:
                label = mem_type_names.get(idx, f"mem[{idx}]")
                print(
                    "  %-16s base 0x%-16x size 0x%-8x end 0x%-16x"
                    % (label, base, size, base + size),
                    file=self.f,
                )

            print("", file=self.f)

    def write_module_cmm(self):
        t32_modules_script = self.ramdump.open_file('t32_modules_script.cmm')
        for mod_tbl_ent in self.ramdump.module_table.module_table:
            mod_sym_path = mod_tbl_ent.get_sym_path()
            if mod_sym_path != '':
                ld_mod_sym = ''
                where = os.path.abspath(mod_sym_path)
                if self.ramdump.minidump:
                    ld_mod_sym = "Data.LOAD.Elf " + where + " /NoClear /CODESEC /RELOC .text at " + str(hex(mod_tbl_ent.module_offset))
                    if mod_tbl_ent.section_offsets:
                        if ".data" in mod_tbl_ent.section_offsets.keys():
                            ld_mod_sym += " /RELOC .data at " + str(hex(mod_tbl_ent.section_offsets['.data']))
                        if ".bss" in mod_tbl_ent.section_offsets.keys() :
                            ld_mod_sym += " /RELOC .bss at " + str(hex(mod_tbl_ent.section_offsets['.bss']))
                    ld_mod_sym += "\n"
                elif 'wlan' in mod_tbl_ent.name:
                    ld_mod_sym = "Data.LOAD.Elf " + where + " " + str(hex(mod_tbl_ent.module_offset)) +  " /NoCODE /NoClear /NAME " + mod_tbl_ent.name + " /reloctype 0x3" + "\n"
                else:
                    ld_mod_sym = "Data.LOAD.Elf " + where + " /NoCODE /NoClear /NAME " + mod_tbl_ent.name + " /reloctype 0x3" + "\n"
                t32_modules_script.write(ld_mod_sym)
        t32_modules_script.close()
    def parse(self):
        self.write_module_cmm()
        if self.ramdump.minidump:
            return

        self.module_table_cn = self.ramdump.module_table
        self.f = self.ramdump.open_file('modules_table.txt')
        self.f.write(
            "%-32s %-18s %-18s %-16s %-10s %-18s %-30s %-18s %-18s\n"
            % ("MODULE", "CORE_BASE", "struct_module", "scmversion",
               "state", "init_addr", "init_symbol", "mod_start", "mod_end")
        )
        self.modules_list = []
        self.retrieve_modules_cn()
        self.f.close()