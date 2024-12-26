# Copyright (c) 2025 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: GPL-2.0-only

import traceback
from print_out import print_out_str
from parser_util import register_parser, RamParser
import json


@register_parser(
    '--bcl-info', 'Useful information from BCL data structures')
class BCL_info(RamParser):
    def __init__(self, dump):
        super(BCL_info, self).__init__(dump)

    def write_to_text(self,device_stats_dict):
        formatted_data = json.dumps(device_stats_dict,indent=4)
        self.writeln(f"{formatted_data}")

    def write_to_json(self,device_stats_dict):
        #Write the dictionary to a json file
        with self.ramdump.open_file('bcl_info/bcl_peripheral_stats.json',"w") as json_file:   #json_file is a file object that will close after the with open(...)
            json.dump(device_stats_dict,json_file,indent=4)

    def write(self, string):
        self.out.write(string)

    def writeln(self, string=""):
        self.out.write(string + '\n')

    def parse(self):
        print_out_str("Started bcl parsing")
        self.out = self.ramdump.open_file('bcl_info/bcl_stats.txt', "w")
        try:
            self.write("BCL DATA".center(90, '-') + '\n')
            self.writeln()
            cnt = self.ramdump.read_int("bcl_device_ct")
            self.writeln(f"bcl_device_cnt:{cnt}")

            bcl_device_dict = {}

            for i in range(cnt):
                bcl_ptr = self.ramdump.read_pointer(f"bcl_devices[{i}]")

                if not bcl_ptr:
                    self.writeln(f"bcl_devices[{i}] is NULL")
                    continue

                self.writeln(f"bcl_devices_address:({hex(bcl_ptr)})")

                device_key = f"bcl_devices[{i}]"
                device_data = {"stats": {}}

                try:
                    bcl_device = self.ramdump.read_datatype(bcl_ptr,"struct bcl_device")
                    if bcl_device is None:
                        raise ValueError(f"Failed to read struct device at address: {hex(bcl_ptr)}")
                except Exception as e:
                    self.writeln(f"Error reading struct device at address {hex(bcl_ptr)}")
                    device = None

                try:
                    # if stats pointer not present, return
                    _stats_data = bcl_device.stats
                    if not _stats_data:
                        self.writeln(f"bcl_devices[{i}] dont have stats data")
                        continue
                except:
                    self.writeln(f"bcl_devices[{i}] dont have stats data")
                    continue

                #Iterate over stats array in the device
                try:
                    for j, stat_ptr in enumerate(bcl_device.stats):
                        if stat_ptr:
                            try:
                                stats_data = {
                                    "counter": bcl_device.stats[j].counter,
                                    "self_cleared_counter": bcl_device.stats[j].self_cleared_counter,
                                    "max_mitig_ts(nsec)": bcl_device.stats[j].max_mitig_ts,
                                    "max_mitig_latency(usec)": bcl_device.stats[j].max_mitig_latency,
                                    "max_duration(usec)": bcl_device.stats[j].max_duration,
                                    "total_duration(usec)": bcl_device.stats[j].total_duration,
                                    "bcl_history": {}
                                }

                                for k, history in enumerate(bcl_device.stats[j].bcl_history):
                                    try:
                                        history_key = f"bcl_history[{k}]"
                                        stats_data["bcl_history"][history_key] = {
                                            "vbat(mV)": history.vbat,
                                            "ibat(mA)": history.ibat,
                                            "trigger_ts(nsec)": history.trigger_ts,
                                            "clear_ts(nsec)": history.clear_ts
                                        }
                                    except Exception as e:
                                        self.writeln(f"Failed to process bcl_history[{k}] in stats[{j}]: {e}")
                                stat_key = f"stats[{j}]"
                                device_data["stats"][stat_key] = stats_data
                            except Exception as e:
                                self.writeln(f"Failed to process stats[{j}]: {e}")
                except Exception as e:
                    self.writeln(f"Error occured while iterating over device.stats: {e}")

                bcl_device_dict[device_key] = device_data

            if bcl_device_dict:
                # self.write_to_text(device_stats_dict)
                self.write_to_text(bcl_device_dict)

                # write the dictionary to a json file
                results = self.convert_dict_to_list(bcl_device_dict)
                self.write_to_json(results)
        except Exception as e:
            self.writeln(traceback.format_exc())

        # close text file
        self.out.close()
        print_out_str("Done bcl parsing")

    def convert_dict_to_list(self,input_dict):
        result = {"bcl_devices": []}
        try:
            for device_key, device_value in input_dict.items():
                device_name = device_key.replace("bcl_devices[0]", "bcl_0x4700_0").replace("bcl_devices[1]", "bcl_0x4700_1")
                device = {"name": device_name, "stats": []}
                for stat_key, stat_value in device_value["stats"].items():
                    try:
                        bcl_level = int(stat_key.split('[')[1].split(']')[0])
                        stat = {
                            "bcl_level": bcl_level,
                            "counter": stat_value["counter"],
                            "self_cleared_counter": stat_value["self_cleared_counter"],
                            "max_mitig_ts(nsec)": stat_value["max_mitig_ts(nsec)"],
                            "max_mitig_latency(usec)": stat_value["max_mitig_latency(usec)"],
                            "max_duration(usec)": stat_value["max_duration(usec)"],
                            "total_duration(usec)": stat_value["total_duration(usec)"],
                            "bcl_history": []
                        }
                        for history_key, history_value in stat_value["bcl_history"].items():
                            history = {
                                "vbat(mV)": history_value["vbat(mV)"],
                                "ibat(mA)": history_value["ibat(mA)"],
                                "trigger_ts(nsec)": history_value["trigger_ts(nsec)"],
                                "clear_ts(nsec)": history_value["clear_ts(nsec)"]
                            }
                            stat["bcl_history"].append(history)
                        device["stats"].append(stat)
                    except Exception as e:
                        self.writeln(f"Error processing stat {stat_key}: {e}")
                result["bcl_devices"].append(device)
        except Exception as e:
            self.writeln(f"Error processing device {device_key}: {e}")
        return result

