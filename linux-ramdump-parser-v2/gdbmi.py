# Copyright (c) 2013-2020, The Linux Foundation. All rights reserved.
# Copyright (c) 2022-2024, Qualcomm Innovation Center, Inc. All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 and
# only version 2 as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

import sys
import re
import subprocess
import module_table
from print_out import print_out_str
from tempfile import NamedTemporaryFile

GDB_SENTINEL = '(gdb) '
GDB_DATA_LINE = '~'
GDB_OOB_LINE = '^'


def gdb_hex_to_dec(val):
    match = re.search('(0x[0-9a-fA-F]+)', val)
    return int(match.group(1), 16)


class GdbSymbol(object):

    def __init__(self, symbol, section, addr, offset=None):
        self.symbol = symbol
        self.section = section
        self.addr = addr
        if offset is not None:
            self.offset = offset

class GdbMIResult(object):

    def __init__(self, lines, oob_lines):
        self.lines = lines
        self.oob_lines = oob_lines


class GdbMIException(Exception):

    def __init__(self, *args):
        self.value = '\n *** '.join([str(i) for i in args])

    def __str__(self):
        return self.value


class GdbMI(object):
    """Interface to the ``gdbmi`` subprocess. This should generally be
    used as a context manager (using Python's ``with`` statement),
    like so::

        >>> with GdbMI(gdb_path, elf) as g:
                print('GDB Version: ' + g.version())
    """

    def __init__(self, gdb_path, elf, kaslr_offset=0):
        self.gdb_path = gdb_path
        self.elf = elf
        self.kaslr_offset = kaslr_offset
        self._cache = {}
        self._gdbmi = None
        self.mod_table = None
        self.gdbmi_aslr_offset = 0

    def open(self):
        """Open the connection to the ``gdbmi`` backend. Not needed if using
        ``gdbmi`` as a context manager (recommended).
        """
        if sys.platform.startswith("win"):
            import ctypes
            SEM_NOGPFAULTERRORBOX = 0x0002 # From MSDN
            ctypes.windll.kernel32.SetErrorMode(SEM_NOGPFAULTERRORBOX);
            subprocess_flags = 0x8000000 #win32con.CREATE_NO_WINDOW?
        else:
            subprocess_flags = 0

        self._gdbmi = subprocess.Popen(
            [self.gdb_path, '--interpreter=mi2', self.elf],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            universal_newlines=True,
            creationflags=subprocess_flags
        )
        self._flush_gdbmi()
        self._run('set max-value-size unlimited')

    def close(self):
        """Close the connection to the ``gdbmi`` backend. Not needed if using
        ``gdbmi`` as a context manager (recommended).

        """

        if not self._gdbmi:
            return

        cmd = 'quit'
        self._run(cmd)
        self._gdbmi.kill()
        self._gdbmi = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, ex_type, ex_value, ex_traceback):
        self.close()

    def _flush_gdbmi(self):
        while True:
            line = self._gdbmi.stdout.readline().rstrip('\r\n')
            if line == GDB_SENTINEL:
                break

    def setup_module_table(self, module_table):
        self.mod_table = module_table
        for mod in self.mod_table.module_table:
            if not mod.get_sym_path():
                continue
            load_mod_sym_cmd = ['add-symbol-file', mod.get_sym_path().replace('\\', '\\\\')]
            if ".text" not in mod.section_offsets.keys():
                load_mod_sym_cmd += ['0x{:x}'.format(mod.module_offset - self.kaslr_offset)]
            for segment, offset in mod.section_offsets.items():
                load_mod_sym_cmd += ['-s', segment, '0x{:x}'.format(offset - self.kaslr_offset) ]
            self._run(' '.join(load_mod_sym_cmd))

    def _run(self, cmd, skip_cache=False, save_in_cache=True):
        """Runs a gdb command and returns a GdbMIResult of the result. Results
        are cached (unless skip_cache=True) for quick future lookups.

        - cmd: Command to run (e.g. "show version")
        - skip_cache: Don't use a previously cached result
        - save_in_cache: Whether we should save this result in the cache

        """
        if self._gdbmi is None:
            raise Exception(
                'BUG: GdbMI not initialized. ' +
                'Please use GdbMI.open or a context manager.')

        if not skip_cache:
            if cmd in self._cache:
                return GdbMIResult(self._cache[cmd], [])

        output = []
        oob_output = []
        try:
            self._gdbmi.stdin.write(cmd.rstrip('\n') + '\n')
            self._gdbmi.stdin.flush()
        except Exception as err:
            return GdbMIResult(output, oob_output)

        while True:
            line = self._gdbmi.stdout.readline()
            """
            readline blocks, unless the pipe is closed on the other end, in which case it
            returns an empty line, without trailing \n.
            """
            if not len(line):
                break

            line = line.rstrip('\r\n')
            if line == GDB_SENTINEL:
                break
            if line.startswith(GDB_DATA_LINE):
                # strip the leading "~"
                line = line[1:]
                # strip the leading and trailing "
                line = line[1:-1]
                if line.startswith("\\n"):
                    continue
                # strip any trailing (possibly escaped) newlines
                if line.endswith('\\n'):
                    line = line[:-2]
                elif line.endswith('\n'):
                    line = line.rstrip('\n')
                output.append(line)
            if line.startswith(GDB_OOB_LINE):
                oob_output.append(line[1:])

        if save_in_cache:
            self._cache[cmd] = output

        return GdbMIResult(output, oob_output)

    def _run_for_one(self, cmd):
        result = self._run(cmd)
        if len(result.lines) != 1:
            raise GdbMIException(
                cmd, '\n'.join(result.lines + result.oob_lines))
        return result.lines[0]

    def _run_for_first(self, cmd):
        return self._run(cmd).lines[0]

    def _run_for_multi(self, cmd):
        result = self._run(cmd)
        return result.lines

    def version(self):
        """Return GDB version"""
        return self._run_for_first('show version')

    def set_gdbmi_aslr_offset(self):
        """set gdb aslr offset"""
        try:
            lines = self._run('maintenance info sections').lines
            for line in lines:
                if re.search(".head.text ALLOC", line):
                    text_addr = int(self._run_for_one('print /x &_text').split(' ')[-1], 16)
                    if len(line.split("->")[0]) > 1 :
                        head_text_addr =  int(line.split("->")[0].split() [-1], 16)
                    else:
                        head_text_addr = int(line.split("->")[0], 16)
                    aslr_offset = head_text_addr - text_addr
                    if aslr_offset != 0:
                        self.gdbmi_aslr_offset = aslr_offset
                    print_out_str("gdbmi_aslr_offset : 0x{0:x}".format(self.gdbmi_aslr_offset))
                    break
        except Exception as err:
            print (err)
            self.gdbmi_aslr_offset = 0

    def setup_aarch(self,type):
        self.aarch_set = True
        cmd = 'set architecture ' + type
        result = self._run_for_one(cmd)
        return

    def getStructureData(self, the_type):
        cmd = 'ptype /o {0}'.format(the_type)
        result = self._run_for_multi(cmd)
        return result

    def get_structure_members(self, struct_name):
        """
        Parses GDB's 'ptype /o' output to extract DIRECT members only.

        GDB's ptype /o expands all nested structs inline (all fields carry
        /* offset | size */ prefixes regardless of nesting depth).  We track
        brace depth so that only depth-1 fields are returned as direct members.

        Named embedded struct/union closing lines  '} fieldname;'  supply the
        field name; their opening line  '/* off | sz */  struct foo {'  supplies
        the offset and size.  Anonymous struct/union members (closed by just
        '};') are promoted to the parent level so that e.g. spinlock_t fields
        inside an anonymous union still appear.

        Returns: {name: {type, offset, size, array_size, is_pointer, is_struct}}
        """
        cmd = 'ptype /o {0}'.format(struct_name)
        try:
            result_lines = self._run_for_multi(cmd)
            if not result_lines:
                return {}
        except GdbMIException:
            return {}

        members = {}

        # Matches a normal field line at any depth:
        #   /* offset[:bit] | size */   type *name[N] : bits;
        field_regex = re.compile(
            r'/\*\s*(\d+)(?::\d+)?\s*\|\s*(\d+)\s*\*/\s+'
            r'(.*?)\b(\w+)(?:\[(\d+)\])?(?:\s*:\s*\d+)?\s*;\s*$'
        )
        # Matches a function-pointer member (field_regex can't handle these):
        #   /* offset | size */   returntype (*fieldname)(params);
        funcptr_regex = re.compile(
            r'/\*\s*(\d+)(?::\d+)?\s*\|\s*(\d+)\s*\*/\s+'
            r'(.*?)\(\s*\*\s*(\w+)\s*\)\s*\('
        )
        # Matches an embedded struct/union opening with an offset comment:
        #   /* offset | size */   struct foo {   or   /* offset | size */  union {
        open_regex = re.compile(
            r'/\*\s*(\d+)(?::\d+)?\s*\|\s*(\d+)\s*\*/\s+'
            r'((?:struct|union)\b\s*\w*)\s*\{'
        )
        # Fallback for anonymous-union members that GDB emits without /* offset | size */:
        #   char *buf;  or  struct etr_buf *etr_buf;
        bare_field_regex = re.compile(
            r'^\s+(.*)\b(\w+)(?:\[(\d+)\])?\s*(?::\s*\d+)?\s*;$'
        )

        depth = 0
        # Stack entry: (offset, size, type_str) for named opens,
        # (offset, size, None) for anonymous opens with offset info,
        # or None for opens without offset info.
        struct_stack = []

        def _add(offset, size, ftype, fname, arr):
            ftype = ftype.strip()
            is_ptr = '*' in ftype
            is_strc = (
                (ftype.startswith('struct ') or ftype.startswith('union ')
                 or ftype in ('struct', 'union'))
                and not is_ptr
            )
            members[fname] = {
                'type': ftype,
                'offset': offset,
                'size': size,
                'array_size': arr,
                'is_pointer': is_ptr,
                'is_struct': is_strc,
            }

        for line in result_lines:
            stripped = line.strip()

            # ── Opening brace ────────────────────────────────────────────────
            if stripped.endswith('{'):
                m = open_regex.search(line)
                if m:
                    type_str = m.group(3).strip()
                    # anonymous struct/union: keyword only, no type name
                    is_anon = type_str in ('struct', 'union')
                    struct_stack.append(
                        (int(m.group(1)), int(m.group(2)), None) if is_anon
                        else (int(m.group(1)), int(m.group(2)), type_str)
                    )
                else:
                    struct_stack.append(None)
                depth += 1
                continue

            # ── Closing brace ─────────────────────────────────────────────────
            if stripped.startswith('}'):
                depth -= 1
                close_m = re.match(r'\}\s*(\w+)\s*;', stripped)
                entry = struct_stack.pop() if struct_stack else None

                if close_m:
                    # Named close: '} fieldname;' — use saved offset/size/type
                    if depth == 1 and entry and entry[2] is not None:
                        off, sz, ftype = entry
                        _add(off, sz, ftype, close_m.group(1), 0)
                else:
                    # Anonymous close '};' — promote its captured fields upward.
                    # They were collected while depth > 1, so re-scan is not
                    # needed: fields captured BELOW this depth are already in
                    # `members` because we do NOT filter by depth for anonymous
                    # containers (see the capture block below).
                    pass
                continue

            # ── Field line ───────────────────────────────────────────────────
            # Capture depth-1 fields directly.
            # Also capture fields inside anonymous structs/unions (where the
            # enclosing open has no name) so that e.g. spinlock_t anonymous
            # inner union members are visible.
            at_named_depth = (depth == 1)
            in_anonymous = (
                depth > 1
                and struct_stack
                and (struct_stack[-1] is None or struct_stack[-1][2] is None)
            )
            if at_named_depth or in_anonymous:
                m = field_regex.search(line)
                if m:
                    _add(int(m.group(1)), int(m.group(2)),
                         m.group(3), m.group(4),
                         int(m.group(5)) if m.group(5) else 0)
                else:
                    fp = funcptr_regex.search(line)
                    if fp:
                        _add(int(fp.group(1)), int(fp.group(2)),
                             fp.group(3).strip() + '(*)()', fp.group(4), 0)
                    elif in_anonymous:
                        parent = struct_stack[-1] if struct_stack else None
                        if parent is not None:
                            bare_m = bare_field_regex.search(line)
                            if bare_m:
                                _add(parent[0], parent[1],
                                     bare_m.group(1), bare_m.group(2),
                                     int(bare_m.group(3)) if bare_m.group(3) else 0)

        return members


    def frame_field_offset(self, frame_name, the_type, field):
        """Returns the offset of a field in a struct or type of selected frame
        if there are two vairable with same na,e in source code.
        """
        cmd = 'frame 0 {0}'.format(frame_name)
        self._run_for_one(cmd)
        cmd = 'print /x (int)&(({0} *)0)->{1}'.format(the_type, field)
        result = self._run_for_one(cmd)
        return gdb_hex_to_dec(result)

    def type_of(self, symbol):
        """ Returns the type of symbol.

        Example:
        >>> gdbmi.type_of("kgsl_driver")
        struct kgsl_driver
        """
        cmd = 'print &{0}'.format(symbol)
        result = self._run_for_one(cmd)
        return result.split("*)")[0].split("= (")[1]

    def print_type(self, type_or_var):
        cmd = 'ptype {0}'.format(type_or_var)
        result = self._run(cmd)
        result = '\n'.join(result.lines)
        if len(result) > 0:
            ptype = result.split("=")[1].strip()
            return ptype
        return None

    def field_offset(self, the_type, field):
        """Returns the offset of a field in a struct or type.

        Example:

        >>> gdbmi.field_offset("struct ion_buffer", "heap")
        20

        ``the_type``
           struct or type (note that if it's a struct you should
           include the word ``"struct"`` (e.g.: ``"struct
           ion_buffer"``))

        ``field``
           the field whose offset we want to return

        """
        cmd = 'print /x (int)&(({0} *)0)->{1}'.format(the_type, field)
        result = self._run_for_one(cmd)
        return gdb_hex_to_dec(result)

    def container_of(self, ptr, the_type, member):
        """Like ``container_of`` from the kernel."""
        return ptr - self.field_offset(the_type, member)

    def sibling_field_addr(self, ptr, parent_type, member, sibling):
        """Returns the address of a sibling field within the parent
        structure.

        Example:

        Given a dump containing an instance of the following struct::

            struct pizza {
                int price;
                int qty;
            };

        If you have a pointer to qty, you can get a pointer to price with:

        >>> addr = sibling_field_addr(qty, 'struct pizza', 'qty', 'price')
        >>> price = dump.read_int(addr)
        >>> price
        10
        """
        return self.container_of(ptr, parent_type, member) + \
            self.field_offset(parent_type, sibling)

    def sizeof(self, the_type):
        """Returns the size of the type specified by ``the_type``."""
        result = self._run_for_one('print /x sizeof({0})'.format(the_type))
        return gdb_hex_to_dec(result)

    def address_of(self, symbol):
        """Returns the address of the specified symbol.

        >>> hex(dump.address_of('linux_banner'))
        '0xc0b0006a'
        """
        result = self._run_for_one('print /x &{0}'.format(symbol))
        addr =  int(result.split(' ')[-1], 16) + self.kaslr_offset + self.gdbmi_aslr_offset
        if (addr >> 64):
            return addr - self.gdbmi_aslr_offset
        else:
            return addr

    def address_of_symbol_from_file(self, symbol, file_name):
        """Returns the address of the specified symbol, from a specific
        driver file. Must skip cache to fix the case where the same
        symbol is defined by 2 files"""

        cmd = 'print /x &\'{0}\'::{1}'.format(file_name, symbol)
        result = self._run(cmd, skip_cache=True, save_in_cache=False)
        if len(result.lines) != 1:
            raise GdbMIException(
                cmd, '\n'.join(result.lines + result.oob_lines))

        result = result.lines[0]
        addr =  int(result.split(' ')[-1], 16) + self.kaslr_offset + self.gdbmi_aslr_offset
        if (addr >> 64):
            return addr - self.gdbmi_aslr_offset
        else:
            return addr

    def get_symbol_info(self, address):
        """Returns a GdbSymbol representing the nearest symbol found at
        ``address``."""
        result = self._run_for_one('info symbol ' + hex(address))
        parts = result.split(' ')
        if len(parts) < 2:
            raise GdbMIException('Output looks bogus...', result)
        symbol = parts[0]
        section = parts[-1]
        try:
            offset = int(parts[1] + parts[2])
        except ValueError:
            offset = 0
        return GdbSymbol(symbol, section, address, offset)

    def symbol_at(self, address):
        """Get the symbol at the given address (using ``get_symbol_info``)"""
        return self.get_symbol_info(address).symbol

    def get_enum_name(self, enum, val):
        result = self._run_for_first('print ((enum {0}){1})'.format(enum, val))
        parts = result.split(' ')
        if len(parts) < 3:
            raise GdbMIException(
                "can't parse enum {0} {1}\n".format(enum, val), result)
        return parts[2].rstrip()

    def get_enum_lookup_table(self, enum, upperbound):
        """Return a table translating enum values to human readable
        strings.

        >>> dump.gdbmi.get_enum_lookup_table('ion_heap_type', 10)
        ['ION_HEAP_TYPE_SYSTEM',
         'ION_HEAP_TYPE_SYSTEM_CONTIG',
         'ION_HEAP_TYPE_CARVEOUT',
         'ION_HEAP_TYPE_CHUNK',
         'ION_HEAP_TYPE_CUSTOM',
         'ION_NUM_HEAPS',
         '6',
         '7',
         '8',
         '9']
        """
        table = []
        for i in range(0, upperbound):
            result = self._run_for_first(
                'print ((enum {0}){1})'.format(enum, i))
            parts = result.split(' ')
            if len(parts) < 3:
                raise GdbMIException(
                    "can't parse enum {0} {1}\n".format(enum, i), result)
            table.append(parts[2].rstrip())

        return table

    def get_func_info(self, address):
        """Returns the function info at a particular address, specifically
        line and file.

        >>> dump.gdbmi.get_func_info(dump.gdbmi.address_of('panic'))
        'Line 78 of \\"kernel/kernel/panic.c\\"'

        """
        address = address - self.kaslr_offset
        result = self._run_for_one('info line *0x{0:x}'.format(address))
        m = re.search(r'(Line \d+ of \\?\".*\\?\")', result)
        if m is not None:
            return m.group(0)
        else:
            return '(unknown info for address 0x{0:x})'.format(address)

    def get_value_of(self, symbol):
        """Returns the value of a symbol (in decimal)"""
        result = self._run_for_one('print /d {0}'.format(symbol))
        return int(result.split(' ')[-1], 10)


    def get_value_of_string(self, symbol):
        """Returns the value of a symbol (as a string)"""
        self._run("set print elements 0")
        cmd = 'print /s {0}'.format(symbol)
        result = self._run(cmd)
        if len(result.lines) == 0:
            raise GdbMIException(
                            cmd, '\n'.join(result.lines + result.oob_lines))
        match = re.search(r'^[$]\d+ = \\"(.*)(\\\\n\\")', result.lines[0])
        match_1 = re.search(r'^[$]\d+ = 0x[0-9a-fA-F]+ .* \\"(.*)(\\\\n\\")', result.lines[0])
        match_2 = re.search(r'^[$]\d+ = 0x[0-9a-fA-F]+ \\"(.*)(\\\\n\\")', result.lines[0])
        if match:
            return match.group(1).replace('\\\\n\\"',"")
        elif match_1:
            return match_1.group(1)
        elif match_2:
            return match_2.group(1).replace('\\\\n\\"', "")
        elif result.lines[0] != None:
            return result.lines[0]
        else:
            return None

    def read_memory(self, start, end):
        """Reads memory from within elf (e.g. const data). start and end should be kaslr-offset values"""
        tmpfile = NamedTemporaryFile(mode='rb')
        self._run("dump binary memory {} {}-{} {}-{}".format(tmpfile.name, start, self.kaslr_offset, end, self.kaslr_offset))
        return tmpfile.read()

    def read_elf_memory(self, start, end, temp_file):
        self._run("dump binary memory {} {} {}".format(temp_file.name, start, end))
        return temp_file.read()

    def set_priority_namespace(self, filename):
        """Set specific file as priority namespace for symbol identification"""
        self._run("list \'{0}\':1".format(filename), skip_cache=True, save_in_cache=False)

        """ Clear all cached results with other namespace """
        self._cache = dict()
        return None


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('Usage: gdbmi.py gdb_path elf')
        sys.exit(1)

    gdb_path, elf = sys.argv[1:]

    with GdbMI(gdb_path, elf) as g:
        print('GDB Version: ' + g.version())
        print('ion_buffer.heap offset: ' + str(g.field_offset('struct ion_buffer', 'heap')))
        print('atomic_t.counter offset: ' + str(g.field_offset('atomic_t', 'counter')))
        print('sizeof(struct ion_buffer): ' + str(g.sizeof('struct ion_buffer')))
        addr = g.address_of('kernel_config_data')
        print('address of kernel_config_data: ' + hex(addr))
        symbol = g.get_symbol_info(addr)
        print('symbol at ' + hex(addr) + ' : ' + symbol.symbol + \
            ' which is in section ' + symbol.section)
