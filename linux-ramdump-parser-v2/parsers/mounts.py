# SPDX-License-Identifier: GPL-2.0-only
# Copyright (c) 2024 Qualcomm Innovation Center, Inc. All rights reserved.
from parser_util import register_parser, RamParser, cleanupString
from print_out import print_out_str
from utasklib import UTaskLib
from utasklib import ProcessNotFoundExcetion
import linux_list as llist
from collections import namedtuple

class BaseFs(RamParser):

    def __init__(self, ramdump):
        super().__init__(ramdump)
        self.mnt_tuple = namedtuple("MntTuple", ["mount", "vfsmount", "super_block", "dname", "mpath"])

    def get_dname_of_dentry(self, dentry):
        dentry_name_offset = self.ramdump.field_offset(
            'struct dentry', 'd_name')
        len_offset = self.ramdump.field_offset(
            'struct qstr', 'len')
        qst_name_offset = self.ramdump.field_offset(
            'struct qstr', 'name')

        name_address = self.ramdump.read_word(dentry + dentry_name_offset + qst_name_offset)
        len_address = dentry + dentry_name_offset + len_offset
        len = self.ramdump.read_u32(len_address)
        name = cleanupString(self.ramdump.read_cstring(name_address, len))
        return name

    def get_pathname(self, vfsmount):
        mnt_root = self.ramdump.read_structure_field(vfsmount, 'struct vfsmount', 'mnt_root')

        mnt_offset_in_mount = self.ramdump.field_offset('struct mount', 'mnt')
        mnt_parent_offset = self.ramdump.field_offset('struct mount', 'mnt_parent')
        mount = vfsmount - mnt_offset_in_mount
        mnt_mountpoint_offset = self.ramdump.field_offset(
            'struct mount', 'mnt_mountpoint')
        d_parent_offset = self.ramdump.field_offset(
            'struct dentry', 'd_parent')
        mnt_parent_pre = 0
        mnt_parent = mount
        mount_name = []
        while  mnt_parent_pre != mnt_parent:
            mnt_parent_pre = mnt_parent
            mnt_mountpoint =  self.ramdump.read_word(mnt_parent + mnt_mountpoint_offset)
            name = self.get_dname_of_dentry(mnt_mountpoint)
            mnt_parent = self.ramdump.read_word(mnt_parent + mnt_parent_offset)
            if name == None or name == '/':
                break
            if mnt_parent == 0:
                break
            mount_name.append(name)

            # walk to get the fullname of mountpoint
            d_parent = self.ramdump.read_word(mnt_mountpoint + d_parent_offset)
            d_parent_pre = 0
            while d_parent_pre != d_parent:
                d_parent_pre = d_parent
                name = self.get_dname_of_dentry(d_parent)
                d_parent = self.ramdump.read_word(d_parent + d_parent_offset)
                if name == None or name == '/':
                    break
                mount_name.append(name)
                if d_parent == 0:
                    break

        full_name = ''
        names = []
        for item in mount_name:
            names.append(item)
        names.reverse()
        for item in names:
            full_name += '/' + item
        if len(names) == 0:
            return '/'
        return full_name

    def parse(self):
        pid = 1
        try:
            args = self.parse_param()
            try:
                pid = int(args["pid"])
            except:
                pid = args["proc"]
        except:
            pid = 1
        finally:
            print_out_str("Dump info from process {}".format(pid))

        try:
            taskinfo = UTaskLib(self.ramdump).get_utask_info(pid)
        except ProcessNotFoundExcetion:
            print_out_str("pid={} process is not started".format(pid))
            return

        nsproxy = self.ramdump.read_structure_field(taskinfo.task_addr, 'struct task_struct', 'nsproxy')
        fs = self.ramdump.read_structure_field(taskinfo.task_addr, 'struct task_struct', 'fs')
        root = fs + self.ramdump.field_offset('struct fs_struct', 'root')

        mnt_ns = self.ramdump.read_structure_field(nsproxy, 'struct nsproxy', 'mnt_ns')

        mount_list_addr = mnt_ns + self.ramdump.field_offset("struct mnt_namespace", 'list')
        field_next_offset = self.ramdump.field_offset('struct mount', 'mnt_list')

        self.output.write(f"Process: {taskinfo.name}, (struct task_struct*)=0x{taskinfo.task_addr:x} \
                          (struct nsproxy*)=0x{nsproxy:x} (struct mnt_namespace*)=0x{mnt_ns:x}\n\n\n")
        self.print_header()
        list_walker = llist.ListWalker(self.ramdump, mount_list_addr, field_next_offset)
        list_walker.walk(mount_list_addr, self.__show_info, mount_list_addr)

    def print_header(self):
        pass

    def __show_info(self, mount, mount_list_addr):
        field_next_offset = self.ramdump.field_offset('struct mount', 'mnt_list')
        if mount_list_addr == mount + field_next_offset:
            return

        vfsmount = mount + self.ramdump.field_offset('struct mount', 'mnt')
        d_name_addr = self.ramdump.read_word(mount + self.ramdump.field_offset('struct mount', 'mnt_devname'))
        d_name = self.ramdump.read_cstring(d_name_addr, 48)
        if d_name == "rootfs":
            return
        mount_path = self.get_pathname(vfsmount)
        mnt_root = self.ramdump.read_structure_field(vfsmount, 'struct vfsmount', 'mnt_root')
        sb = self.ramdump.read_structure_field(mnt_root, 'struct dentry', 'd_sb')
        mtuple = self.mnt_tuple(mount, vfsmount, sb, d_name,  mount_path)
        self.show_info(mtuple)

@register_parser('--mount', 'Extract mount info logs from ramdump', optional=True)
class Mount(BaseFs):
    def __init__(self, ramdump):
        super().__init__(ramdump)
        self.output = self.ramdump.open_file("mounts.txt")

    def is_anon_ns(self, mnt_namespace):
        return self.ramdump.read_u64(mnt_namespace, "seq") == 0

    def show_type(self, super_block):
        s_type = self.ramdump.read_structure_field(super_block, "struct super_block", 's_type')
        name = self.ramdump.read_structure_field(s_type, "struct file_system_type", 'name')

        type_name = self.ramdump.read_cstring(name, 24)
        s_subtype = self.ramdump.read_structure_field(super_block, "struct super_block", 's_subtype')

        if s_subtype:
            subname = self.ramdump.read_cstring(s_subtype, 24)
            type_name = type_name + "." + subname
        return type_name

    def mnt_is_readonly(self, vfsmount):
        MNT_READONLY =	0x40
        SB_RDONLY = 1
        self.mnt_flags = self.ramdump.read_int(vfsmount + self.ramdump.field_offset("struct vfsmount", 'mnt_flags'))
        mnt_sb = self.ramdump.read_structure_field(vfsmount, "struct vfsmount", 'mnt_sb')
        self.s_flags = self.ramdump.read_word(mnt_sb + self.ramdump.field_offset('struct super_block', 's_flags'))
        return (self.mnt_flags & MNT_READONLY) or (self.s_flags &SB_RDONLY)

    def show_sb_opts(self, super_block):
        SB_SYNCHRONOUS = 1 << 4
        SB_DIRSYNC = 1 << 7
        SB_MANDLOCK = 1 << 6
        SB_LAZYTIME = 1 << 25
        fs_opts= {
                SB_SYNCHRONOUS : ",sync",
                SB_DIRSYNC : ",dirsync",
                SB_MANDLOCK : ",mand",
                SB_LAZYTIME :",lazytime",
                }
        ret = ""
        for flag, flag_str in fs_opts.items():
            if self.s_flags & flag:
                ret = ret + flag_str

        self.output.write(ret)
        self.selinux_sb_show_options(super_block)

    def selinux_superblock(self, super_block):
        s_security = self.ramdump.read_structure_field(super_block, "struct super_block", 's_security')
        selinux_blob_sizes = self.ramdump.address_of('selinux_blob_sizes')
        try:
            ##lbs_superblock not exist on kernel 5.1
            lbs_superblock = self.ramdump.read_int(
                selinux_blob_sizes + self.ramdump.field_offset("struct lsm_blob_sizes", 'lbs_superblock'))
        except:
            lbs_superblock = 0
        return s_security + lbs_superblock

    def selinux_initialized(self):
        selinux_state = self.ramdump.address_of('selinux_state')
        initialized = self.ramdump.read_bool(
            selinux_state + self.ramdump.field_offset("struct selinux_state", 'initialized'))
        return initialized

    def selinux_sb_show_options(self, super_block):
        SE_SBINITIALIZED =	0x0100

        sbsec = self.selinux_superblock(super_block)
        s_flags = self.ramdump.read_u16(sbsec + self.ramdump.field_offset("struct superblock_security_struct", 'flags'))
        if (s_flags & SE_SBINITIALIZED) == 0:
            return
        if not self.selinux_initialized():
            return

        CONTEXT_MNT =	0x01
        FSCONTEXT_MNT =	0x02
        ROOTCONTEXT_MNT =	0x04
        DEFCONTEXT_MNT =	0x08
        SBLABEL_MNT =	0x10

        CONTEXT_STR =	"context"
        FSCONTEXT_STR =	"fscontext"
        ROOTCONTEXT_STR =	"rootcontext"
        DEFCONTEXT_STR =	"defcontext"
        SECLABEL_STR = "seclabel"
        if s_flags & FSCONTEXT_MNT:
            self.output.write("," + FSCONTEXT_STR)
            return
        if s_flags & CONTEXT_MNT:
            self.output.write("," + CONTEXT_STR)
            return
        if s_flags & DEFCONTEXT_MNT:
            self.output.write("," + DEFCONTEXT_STR)
            return
        if s_flags & ROOTCONTEXT_MNT:
            self.output.write("," + ROOTCONTEXT_STR)
            return
        if s_flags & SBLABEL_MNT:
            self.output.write("," + SECLABEL_STR)
            return

    def show_mnt_opts(self, vfsmount):
        MNT_NOSUID =	0x01
        MNT_NODEV =	0x02
        MNT_NOEXEC =	0x04
        MNT_NOATIME =	0x08
        MNT_NODIRATIME =	0x10
        MNT_RELATIME =	0x20
        MNT_READONLY =	0x40
        MNT_NOSYMFOLLOW =	0x80
        mnt_opts = {
            MNT_NOSUID : ",nosuid",
            MNT_NODEV : ",nodev",
            MNT_NOEXEC : ",noexec",
            MNT_NOATIME : ",noatime",
            MNT_NODIRATIME : ",nodiratime",
            MNT_RELATIME : ",relatime",
            MNT_NOSYMFOLLOW : ",nosymfollow",
		}
        ret = ""
        for flag, flag_str in mnt_opts.items():
            if self.mnt_flags & flag:
                ret = ret + flag_str

        if self.is_idmapped_mnt(vfsmount):
            ret = ret + ",idmapped"
        self.output.write(ret)

    def is_idmapped_mnt(self, vfsmount):
        mnt_idmap = self.ramdump.read_structure_field(vfsmount, "struct vfsmount", 'mnt_idmap')
        nop_mnt_idmap = self.ramdump.address_of('nop_mnt_idmap')
        return mnt_idmap != nop_mnt_idmap

    def print_header(self):
        self.output.write("{:<16s} {:<16s} {:<29s} {:<32s} {:<16s} {:<16s}\n".format(
            "(struct mount *)", "(struct super_block *)", "dev_name", "mount_path", "fs_type", "flags"))

    def show_info(self, mtuple):
        mount = mtuple.mount
        vfsmount = mtuple.vfsmount
        sb = mtuple.super_block
        dname = mtuple.dname
        mount_path = mtuple.mpath

        typename = self.show_type(sb)
        self.output.write("0x{:16x} 0x{:16x} {:<32s} {:<32s} {:<16s} ".format(
                                mount, sb, dname, mount_path, typename))
        if self.mnt_is_readonly(vfsmount):
            self.output.write("ro")
        else:
            self.output.write("rw")

        self.show_sb_opts(sb)
        self.show_mnt_opts(vfsmount)
        self.output.write("\n")