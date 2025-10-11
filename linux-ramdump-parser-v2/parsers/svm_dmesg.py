# SPDX-License-Identifier: GPL-2.0-only
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.

from print_out import print_out_str
from parser_util import RamParser, cleanupString, register_parser
import linux_list as llist
from struct_print import struct_print_class
import parsers.linux_devices as ldevices
import re
import os
import sys
import dmesglib

@register_parser('--print-svmdmesg', 'Print the svmdmesg')
class svmdmesg(RamParser):

    def __init__(self, *args):
        super(svmdmesg, self).__init__(*args)

    def get_svm_device(self, fout):
        device = ldevices.DevicesList(self.ramdump)
        self.device_lists = device.get_device_list()
        for item in self.device_lists:
            name = item[1]
            device_item = item[0]
            if name == None:
                name = 'n/a'
            if 'soc:dmesg-dump' in name:
                drvdata = self.ramdump.read_structure_field(device_item, 'struct device', 'driver_data')
                if drvdata != 0:
                    qcom_dmesg_dumper_address = drvdata
                    qcom_dmesg_dumper = self.ramdump.read_datatype(qcom_dmesg_dumper_address, 'struct qcom_dmesg_dumper')
                    base = qcom_dmesg_dumper.base
                    size = qcom_dmesg_dumper.size
                    log = self.ramdump.get_bin_data(base, size)
                    fout.write(cleanupString(log.decode('ascii', 'ignore')))
                break
    def parse(self):
        self.f = self.ramdump.open_file("svmdmesg.txt")
        self.get_svm_device(self.f)
        self.f.close()

def extract_numbers_from_dmesg(demsg_path, extract_pvm_svm_offset=False):
    svmktime = []
    pvm_svm_offset = []

    svmktime_pattern = re.compile(r'svm ktime=(\d+)')
    pvm_svm_offset_pattern = re.compile(r'pvm_svm_offset=(\d+)')

    with open(demsg_path, 'r') as f:
        dmesg = f.read()

    svmktime_matches = svmktime_pattern.findall(dmesg)
    pvm_svm_offset_matches = pvm_svm_offset_pattern.findall(dmesg) if extract_pvm_svm_offset else []

    svmktime = [int(num) for num in svmktime_matches]
    pvm_svm_offset = [int(num) for num in pvm_svm_offset_matches]

    return svmktime, pvm_svm_offset

def process_svmdmesg(svmdmesg, min_svmktime_ns, max_svmktime_ns, svmktime_p, pvm_svm_offset_p, svmktime_s):
    new_lines = []
    timestamp_pattern = re.compile(r'\[\s*(\d+\.\d+)\]')

    with open(svmdmesg, 'r') as f:
        for line in f:
            match = timestamp_pattern.search(line)
            if match:
                timestamp_sec = float(match.group(1))
                timestamp_ns = int(timestamp_sec * 1e9)
                if timestamp_ns < min_svmktime_ns:
                    line = "[Invalid Time] " + line
                elif timestamp_ns >= min_svmktime_ns and timestamp_ns <= max_svmktime_ns:
                    closest_svmktime = max([ktime for ktime in svmktime_p if ktime <= timestamp_ns])
                    offset_index = svmktime_p.index(closest_svmktime)
                    new_timestamp_ns = timestamp_ns + pvm_svm_offset_p[offset_index]
                    new_timestamp_sec = new_timestamp_ns / 1e9
                    line = f"[{new_timestamp_sec:.6f}] " + line
                else:
                    if max_svmktime_ns in svmktime_s:
                        a = min([ktime for ktime in svmktime_s if ktime > max_svmktime_ns], default=None)
                        if a and timestamp_ns < a:
                            offset_index = svmktime_numbers1.index(max_svmktime_ns)
                            new_timestamp_ns = timestamp_ns + pvm_svm_offset_numbers1[offset_index]
                            new_timestamp_sec = new_timestamp_ns / 1e9
                            line = f"[{new_timestamp_sec:.6f}] " + line
                        else:
                            line = "[Invalid Time] " + line
                    else:
                        line = "[Invalid Time] " + line
            new_lines.append(line)

    return new_lines

def get_svmdmesg_with_pvmktime(svmdmesg, pvmdmesg, output_path):
    svmktime_p, pvm_svm_offset_p = extract_numbers_from_dmesg(pvmdmesg, True)
    svmktime_s, _ = extract_numbers_from_dmesg(svmdmesg, False)

    min_svmktime_ns = min(svmktime_p)
    max_svmktime_ns = max(svmktime_p)

    svmdmesg_with_pvmktime = process_svmdmesg(svmdmesg, min_svmktime_ns, max_svmktime_ns, svmktime_p, pvm_svm_offset_p, svmktime_s)

    with open(output_path, 'w') as f:
        f.writelines(svmdmesg_with_pvmktime)

@register_parser('--svmdmesg-with-pvmktime', 'Print the svmdmesg with pvm ktime')
class svmdmesg_with_pvmktime(RamParser):
    def __init__(self, *args):
        super(svmdmesg_with_pvmktime, self).__init__(*args)

    def parse(self):
        if self.ramdump.svm:
            svmdmesg = self.ramdump.open_file("svmdmesg.txt")
            dmesglib.DmesgLib(self.ramdump, svmdmesg).extract_dmesg()
            svmdmesg.close()

        if self.ramdump.svm:
            pvmdmesg = self.ramdump.dump.open_file("pvmdmesg.txt")
            dmesglib.DmesgLib(self.ramdump.dump, pvmdmesg).extract_dmesg()
            pvmdmesg.close()
            pvmdmesg_path = os.path.join(self.ramdump.dump.outdir, "pvmdmesg.txt")
        else:
            pvmdmesg = self.ramdump.open_file("pvmdmesg.txt")
            dmesglib.DmesgLib(self.ramdump, pvmdmesg).extract_dmesg()
            pvmdmesg.close()
            pvmdmesg_path = os.path.join(self.ramdump.outdir, "pvmdmesg.txt")

        svmdmesg_path = os.path.join(self.ramdump.outdir, "svmdmesg.txt")
        svmdmesg_with_pvmktime_path = os.path.join(self.ramdump.outdir, "svmdmesg_with_pvmktime.txt")
        get_svmdmesg_with_pvmktime(svmdmesg_path, pvmdmesg_path, svmdmesg_with_pvmktime_path)

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python dmesg_dumper.py <path_to_svm_dmesg> <path_to_pvm_dmesg> <output_path>")
        sys.exit(1)

    svm_dmesg = sys.argv[1]
    pvm_dmesg = sys.argv[2]
    output_path = sys.argv[3]

    get_svmdmesg_with_pvmktime(svm_dmesg, pvm_dmesg, output_path)
