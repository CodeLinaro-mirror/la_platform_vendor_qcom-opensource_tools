# Copyright (c) 2015, 2020-2021 The Linux Foundation. All rights reserved.
# Copyright (c) 2022,2025 Qualcomm Innovation Center, Inc. All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 and
# only version 2 as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

from print_out import print_out_str
from parser_util import register_parser, RamParser
import linux_list as llist
import traceback

TSENS_MAX_SENSORS = 16
DEBUG_SIZE = 10
THERMAL_MAX_TRIPS = 12
THERMAL_MAX_CDEVS = 150


@register_parser(
    '--thermal-info', 'Useful information from thermal data structures')
class Thermal_info(RamParser):
    def __init__(self, dump):
        super(Thermal_info, self).__init__(dump)
        # List of all sub-parsers as (func, info, outfile, mode) tuples.
        self.parser_list_5_10 = [
            (self.parse_thremal_zone_data, "ThermalZone", 'thermal_zone.txt', "w"),
            (self.parse_cooling_device_data, "CoolingDevice", 'cooling_device.txt', "w"),
        ]

        self.parser_list_5_4 = [
            (self.parse_thremal_zone_data, "ThermalZone", 'thermal_zone.txt', "w"),
            (self.parse_cooling_device_data, "CoolingDevice", 'cooling_device.txt', "w"),
            (self.parse_tsen_device_data, "Tsensors", 'tsens_info.txt', "w"),
        ]

        self.parser_list_v1 = [
            (self.tmdev_data, "TsensDbgData", 'tsens_dbg_info.txt', "w"),
        ]

    def print_thermal_info(
            self, sensor_dbg_info_start_address, ram_dump,
            time_stamp, sensor_mapping):
        for ncpu in ram_dump.iter_cpus():
            self.writeln(
                "------------------------------------------------")
            self.writeln(
                " TEMPERATURE ENTRIES FOR CPU:{0}".format(
                    int(ncpu)))
            self.writeln(
                "------------------------------------------------")
            cpu_sensor_addr = sensor_dbg_info_start_address + \
                              sensor_mapping[ncpu]
            for i in range(0, 10):
                temp = self.ramdump.read_word(cpu_sensor_addr + (i * 8), True)
                time = self.ramdump.read_word(
                    cpu_sensor_addr + time_stamp + (i * 8), True)
                self.writeln(
                    "Temperature reading -  {0} ".format(int(temp)))
                self.writeln("TimeStamp - {0}\n".format(int(time)))

    def tmdev_data(self, ram_dump):
        sensor_mapping = []
        self.writeln("Thermal sensor data \n")

        tmdev = self.ramdump.address_of('tmdev')
        tmdev_address = self.ramdump.read_word(tmdev, True)
        sensor_dbg_info_size = ram_dump.sizeof('struct tsens_sensor_dbg_info')
        sensor_dbg_info = self.ramdump.field_offset(
            'struct tsens_tm_device',
            'sensor_dbg_info')
        time_stamp = self.ramdump.field_offset(
            'struct tsens_sensor_dbg_info',
            'time_stmp')
        cpus_sensor = self.ramdump.address_of('cpus')
        cpus_sensor_size = ram_dump.sizeof('struct cpu_info')
        sensor_id_offset = self.ramdump.field_offset(
            'struct cpu_info',
            'sensor_id')

        if not all((tmdev, sensor_dbg_info_size, sensor_dbg_info,
                    time_stamp, cpus_sensor, cpus_sensor_size,
                    sensor_id_offset)):
            self.writeln("Not supported for this target yet  :-( \n")
            return

        for i in ram_dump.iter_cpus():
            cpu_sensor_id_address = cpus_sensor + sensor_id_offset
            sensor_id = self.ramdump.read_u32(cpu_sensor_id_address, True)
            cpus_sensor = cpus_sensor + cpus_sensor_size
            sensor_mapping.append((sensor_id - 1) * sensor_dbg_info_size)

        self.print_thermal_info(
            (tmdev_address + sensor_dbg_info),
            ram_dump,
            time_stamp,
            sensor_mapping)

    def tsens_dbg_parse_fields(self, tsens_device_p):
        dev_o = self.ramdump.field_offset('struct tsens_device', 'dev')
        dev = self.ramdump.read_word(dev_o + tsens_device_p)
        kobj_o = self.ramdump.field_offset('struct device', ' kobj')
        kobj = (dev + kobj_o)
        name_o = self.ramdump.field_offset('struct kobject', 'name')
        name_addr = self.ramdump.read_word(name_o + kobj)
        name = self.ramdump.read_cstring(name_addr)
        if name is not None:
            self.writeln("%s" % (name))
            tsens_dbg_o = self.ramdump.field_offset('struct tsens_device', 'tsens_dbg')
            tsens_dbg = tsens_device_p + tsens_dbg_o
            sensor_dbg_info_o = self.ramdump.field_offset('struct tsens_dbg_context', 'sensor_dbg_info')
            sensor_dbg_info = sensor_dbg_info_o + tsens_dbg
            self.writeln('v.v (struct tsens_device)0x{:8x} 0x{:8x}\n'.format(tsens_device_p,
                                                                             sensor_dbg_info))
            for i in range(0, TSENS_MAX_SENSORS):
                idx = self.ramdump.read_u32(self.ramdump.array_index(sensor_dbg_info, 'struct tsens_dbg', i))
                tsens_dbg_addr = self.ramdump.array_index(sensor_dbg_info, 'struct tsens_dbg', i)
                self.writeln("    idx: %d tsens_dbg_addr 0x%x" % (idx, tsens_dbg_addr))
                time_stmp_o = self.ramdump.field_offset('struct tsens_dbg', 'time_stmp')
                temp_o = self.ramdump.field_offset('struct tsens_dbg', 'temp')
                self.writeln("             time_stmp       temp ")
                for j in range(0, DEBUG_SIZE):
                    time_stmp = self.ramdump.read_word(self.ramdump.array_index(time_stmp_o + tsens_dbg_addr,
                                                                                'unsigned long long', j))
                    temp = self.ramdump.read_u64(
                        self.ramdump.array_index(temp_o + tsens_dbg_addr, 'unsigned long', j))
                    self.writeln("             %d   %d" % (time_stmp, temp))

    def parse_cooling_device_fields(self, cdev_struct_addr, thermal_cdev_dict: dict):
        cdev_data_struct = {}
        cdev_id = None
        try:
            if not cdev_struct_addr:
                return

            cdev_data_struct["cdev_struct_addr"] = cdev_struct_addr
            cdev_id = cdev_data_struct["cdev_id"] = self.ramdump.read_s32(cdev_struct_addr +
                                                                          self.ramdump.field_offset(
                                                                              'struct thermal_cooling_device',
                                                                              'id'))
            if cdev_id is None or cdev_id < 0 or cdev_id > THERMAL_MAX_CDEVS:
                return

            cdev_data_struct["cdev_type"] = self.ramdump.read_structure_cstring(cdev_struct_addr,
                                                                                'struct thermal_cooling_device', 'type')
            if not cdev_data_struct["cdev_type"]:
                return

            cdev_data_struct["updated"] = self.ramdump.read_bool(
                self.ramdump.struct_field_addr(cdev_struct_addr, 'struct thermal_cooling_device', 'updated'))
            if cdev_data_struct["updated"] in [0, "0"]:
                cdev_data_struct["updated"] = "False"
            elif cdev_data_struct["updated"] in [1, "1"]:
                cdev_data_struct["updated"] = "True"

            stats_addr = cdev_data_struct["stats_addr"] = self.ramdump.read_structure_field(cdev_struct_addr,
                                                                                            'struct thermal_cooling_device',
                                                                                            'stats')

            cdev_data_struct["devdata"] = self.ramdump.struct_field_addr(cdev_struct_addr,
                                                                         'struct thermal_cooling_device', 'devdata')

            # Read max_state field (note: singular, not plural)
            max_state_offset = self.ramdump.field_offset('struct thermal_cooling_device', 'max_state')
            if max_state_offset:
                cdev_data_struct["max_state"] = self.ramdump.read_structure_field(cdev_struct_addr,
                                                                                  'struct thermal_cooling_device',
                                                                                  'max_state')

            if stats_addr:
                cdev_data_struct["stats_state"] = self.ramdump.read_structure_field(stats_addr,
                                                                                    'struct cooling_dev_stats', 'state')
                cdev_data_struct["stats_total_trans"] = self.ramdump.read_structure_field(stats_addr,
                                                                                          'struct cooling_dev_stats',
                                                                                          'total_trans')
                cdev_data_struct["stats_last_time"] = self.ramdump.read_structure_field(stats_addr,
                                                                                        'struct cooling_dev_stats',
                                                                                        'last_time')
        except Exception as e:
            cdev_data_struct["exception"] = str(e)

        if cdev_data_struct and cdev_id is not None:
            thermal_cdev_dict[cdev_id] = cdev_data_struct
        return

    def parse_thermal_zone_fields(self, tz_device_addr, thermal_tzone_dict: list, triggered_zones: list):
        tzone_data_dict = {}
        tzone_id = None
        try:
            if not tz_device_addr:
                return

            tzone_data_dict["tz_device_addr"] = hex(tz_device_addr)
            tzone_id = tzone_data_dict["tzone_id"] = self.ramdump.read_s32(tz_device_addr + self.ramdump.field_offset(
                'struct thermal_zone_device', 'id'))
            tzone_data_dict["mode"] = self.ramdump.read_structure_field(tz_device_addr,
                                                                        'struct thermal_zone_device', 'mode')
            if tzone_data_dict["mode"] not in [0, 1]:
                return
            type_addr = self.ramdump.struct_field_addr(tz_device_addr, 'struct thermal_zone_device', 'type')
            tzone_data_dict["type"] = self.ramdump.read_cstring(type_addr)

            # Read governor name - governor is a pointer to struct thermal_governor
            governor_offset = self.ramdump.field_offset('struct thermal_zone_device', 'governor')
            if governor_offset:
                # First read the pointer to the governor structure
                governor_ptr = self.ramdump.read_pointer(tz_device_addr + governor_offset)
                if governor_ptr:
                    # Then read the name field from the governor structure
                    tzone_data_dict["algo_type"] = self.ramdump.read_structure_cstring(governor_ptr,
                                                                                       'struct thermal_governor', 'name')
                else:
                    tzone_data_dict["algo_type"] = None
            else:
                tzone_data_dict["algo_type"] = None

            # Try new field names first (kernel 5.10+), fallback to old names
            filed_offset = self.ramdump.field_offset('struct thermal_zone_device', 'polling_delay_jiffies')
            if filed_offset:
                tzone_data_dict["polling_delay"] = self.ramdump.read_structure_field(tz_device_addr,
                                                                                     'struct thermal_zone_device',
                                                                                     'polling_delay_jiffies')
                tzone_data_dict["passive_delay"] = self.ramdump.read_structure_field(tz_device_addr,
                                                                                     'struct thermal_zone_device',
                                                                                     'passive_delay_jiffies')
            else:
                # Fallback for older kernels (< 5.10)
                tzone_data_dict["polling_delay"] = self.ramdump.read_structure_field(tz_device_addr,
                                                                                     'struct thermal_zone_device',
                                                                                     'polling_delay')
                tzone_data_dict["passive_delay"] = self.ramdump.read_structure_field(tz_device_addr,
                                                                                     'struct thermal_zone_device',
                                                                                     'passive_delay')

            # Read temperature fields with existence checks
            temperature_offset = self.ramdump.field_offset('struct thermal_zone_device', 'temperature')
            if temperature_offset:
                tzone_data_dict["temperature"] = self.ramdump.read_s32(tz_device_addr + temperature_offset)

            last_temperature_offset = self.ramdump.field_offset('struct thermal_zone_device', 'last_temperature')
            if last_temperature_offset:
                tzone_data_dict["last_temperature"] = self.ramdump.read_s32(tz_device_addr + last_temperature_offset)

            emul_temperature_offset = self.ramdump.field_offset('struct thermal_zone_device', 'emul_temperature')
            if emul_temperature_offset:
                tzone_data_dict["emul_temperature"] = self.ramdump.read_s32(tz_device_addr + emul_temperature_offset)

            passive_offset = self.ramdump.field_offset('struct thermal_zone_device', 'passive')
            if passive_offset:
                tzone_data_dict["passive"] = self.ramdump.read_s32(tz_device_addr + passive_offset)

            prev_low_trip_offset = self.ramdump.field_offset('struct thermal_zone_device', 'prev_low_trip')
            if prev_low_trip_offset:
                tzone_data_dict["prev_low_trip"] = self.ramdump.read_s32(tz_device_addr + prev_low_trip_offset)

            prev_high_trip_offset = self.ramdump.field_offset('struct thermal_zone_device', 'prev_high_trip')
            if prev_high_trip_offset:
                tzone_data_dict["prev_high_trip"] = self.ramdump.read_s32(tz_device_addr + prev_high_trip_offset)

            # Read new fields added in kernel 6.0+ if they exist
            recheck_delay_offset = self.ramdump.field_offset('struct thermal_zone_device', 'recheck_delay_jiffies')
            if recheck_delay_offset:
                tzone_data_dict["recheck_delay_jiffies"] = self.ramdump.read_structure_field(tz_device_addr,
                                                                                             'struct thermal_zone_device',
                                                                                             'recheck_delay_jiffies')

            notify_event_offset = self.ramdump.field_offset('struct thermal_zone_device', 'notify_event')
            if notify_event_offset:
                tzone_data_dict["notify_event"] = self.ramdump.read_structure_field(tz_device_addr,
                                                                                    'struct thermal_zone_device',
                                                                                    'notify_event')

            state_offset = self.ramdump.field_offset('struct thermal_zone_device', 'state')
            if state_offset:
                tzone_data_dict["state"] = self.ramdump.read_structure_field(tz_device_addr,
                                                                             'struct thermal_zone_device',
                                                                             'state')

            # Read need_update field only if it exists (removed in kernel 6.0+)
            need_update_offset = self.ramdump.field_offset('struct thermal_zone_device', 'need_update')
            if need_update_offset:
                tzone_data_dict["need_update"] = self.ramdump.read_structure_field(tz_device_addr,
                                                                                   'struct thermal_zone_device',
                                                                                   'need_update')
            # Read trip count - try num_trips first, then ntrips for older kernels
            filed_offset = self.ramdump.field_offset('struct thermal_zone_device', 'num_trips')
            if filed_offset:
                tzone_data_dict["trip_count"] = self.ramdump.read_s32(tz_device_addr +
                                                                      self.ramdump.field_offset(
                                                                          'struct thermal_zone_device', 'num_trips'))
            else:
                # Try 'ntrips' as used in some older kernel versions
                ntrips_offset = self.ramdump.field_offset('struct thermal_zone_device', 'ntrips')
                if ntrips_offset:
                    tzone_data_dict["trip_count"] = self.ramdump.read_s32(tz_device_addr + ntrips_offset)
                else:
                    tzone_data_dict["trip_count"] = 0

            # Read trips_disabled field only if it exists (removed in kernel 6.0+)
            trips_disabled_offset = self.ramdump.field_offset('struct thermal_zone_device', 'trips_disabled')
            if trips_disabled_offset:
                tzone_data_dict["trips_disabled"] = self.ramdump.read_structure_field(tz_device_addr,
                                                                                      'struct thermal_zone_device',
                                                                                      'trips_disabled')

            # Read suspended field - in kernel 6.0+ it's a flag in 'state', in older kernels it's a separate bool
            suspended_offset = self.ramdump.field_offset('struct thermal_zone_device', 'suspended')
            if suspended_offset:
                # Older kernels: separate boolean field
                tzone_data_dict["suspended"] = self.ramdump.read_bool(self.ramdump.struct_field_addr(tz_device_addr,
                                                                                                     'struct thermal_zone_device',
                                                                                                     'suspended'))
                if tzone_data_dict["suspended"] in [0, "0"]:
                    tzone_data_dict["suspended"] = "False"
                elif tzone_data_dict["suspended"] in [1, "1"]:
                    tzone_data_dict["suspended"] = "True"
            elif state_offset:
                # Kernel 6.0+: suspended is a flag (bit 0) in the state field
                # TZ_STATE_FLAG_SUSPENDED = BIT(0) = 0x01
                state_value = tzone_data_dict.get("state", 0)
                if state_value is not None:
                    tzone_data_dict["suspended"] = "True" if (state_value & 0x01) else "False"

            devdata_off = self.ramdump.field_offset('struct thermal_zone_device', 'devdata')
            if devdata_off:
                devdata_off = hex(tz_device_addr + devdata_off)
            tzone_data_dict["devdata"] = devdata_off

            # Read additional kernel 6.0+ list head fields and parse the lists
            trips_high_offset = self.ramdump.field_offset('struct thermal_zone_device', 'trips_high')
            if trips_high_offset:
                tzone_data_dict["trips_high_list"] = hex(tz_device_addr + trips_high_offset)
                tzone_data_dict["trips_high"] = []
                trips_high_list_addr = tz_device_addr + trips_high_offset
                list_node_offset = self.ramdump.field_offset('struct thermal_trip_desc', 'list_node')
                if list_node_offset is not None:
                    trip_walker = llist.ListWalker(self.ramdump, trips_high_list_addr, list_node_offset)
                    for trip_desc_addr in trip_walker:
                        trip_info = {}
                        trip_info["trip_desc_addr"] = hex(trip_desc_addr)
                        trip_info["threshold"] = self.ramdump.read_structure_field(trip_desc_addr,
                                                                                   'struct thermal_trip_desc',
                                                                                   'threshold')
                        # Read trip pointer
                        trip_offset = self.ramdump.field_offset('struct thermal_trip_desc', 'trip')
                        if trip_offset is not None:
                            trip_ptr = trip_desc_addr + trip_offset
                            trip_info["temperature"] = self.ramdump.read_structure_field(trip_ptr,
                                                                                        'struct thermal_trip',
                                                                                        'temperature')
                            trip_info["hysteresis"] = self.ramdump.read_structure_field(trip_ptr,
                                                                                        'struct thermal_trip',
                                                                                        'hysteresis')
                            trip_info["type"] = self.ramdump.read_structure_field(trip_ptr,
                                                                                  'struct thermal_trip',
                                                                                  'type')
                        tzone_data_dict["trips_high"].append(trip_info)

            trips_reached_offset = self.ramdump.field_offset('struct thermal_zone_device', 'trips_reached')
            if trips_reached_offset:
                tzone_data_dict["trips_reached_list"] = hex(tz_device_addr + trips_reached_offset)
                tzone_data_dict["trips_reached"] = []
                trips_reached_list_addr = tz_device_addr + trips_reached_offset
                list_node_offset = self.ramdump.field_offset('struct thermal_trip_desc', 'list_node')
                if list_node_offset is not None:
                    trip_walker = llist.ListWalker(self.ramdump, trips_reached_list_addr, list_node_offset)
                    for trip_desc_addr in trip_walker:
                        trip_info = {}
                        trip_info["trip_desc_addr"] = hex(trip_desc_addr)
                        trip_info["threshold"] = self.ramdump.read_structure_field(trip_desc_addr,
                                                                                   'struct thermal_trip_desc',
                                                                                   'threshold')
                        # Read trip pointer
                        trip_offset = self.ramdump.field_offset('struct thermal_trip_desc', 'trip')
                        if trip_offset is not None:
                            trip_ptr = trip_desc_addr + trip_offset
                            trip_info["temperature"] = self.ramdump.read_structure_field(trip_ptr,
                                                                                        'struct thermal_trip',
                                                                                        'temperature')
                            trip_info["hysteresis"] = self.ramdump.read_structure_field(trip_ptr,
                                                                                        'struct thermal_trip',
                                                                                        'hysteresis')
                            trip_info["type"] = self.ramdump.read_structure_field(trip_ptr,
                                                                                  'struct thermal_trip',
                                                                                  'type')
                        tzone_data_dict["trips_reached"].append(trip_info)

            trips_invalid_offset = self.ramdump.field_offset('struct thermal_zone_device', 'trips_invalid')
            if trips_invalid_offset:
                tzone_data_dict["trips_invalid_list"] = hex(tz_device_addr + trips_invalid_offset)
                tzone_data_dict["trips_invalid"] = []
                trips_invalid_list_addr = tz_device_addr + trips_invalid_offset
                list_node_offset = self.ramdump.field_offset('struct thermal_trip_desc', 'list_node')
                if list_node_offset is not None:
                    trip_walker = llist.ListWalker(self.ramdump, trips_invalid_list_addr, list_node_offset)
                    for trip_desc_addr in trip_walker:
                        trip_info = {}
                        trip_info["trip_desc_addr"] = hex(trip_desc_addr)
                        trip_info["threshold"] = self.ramdump.read_structure_field(trip_desc_addr,
                                                                                   'struct thermal_trip_desc',
                                                                                   'threshold')
                        # Read trip pointer
                        trip_offset = self.ramdump.field_offset('struct thermal_trip_desc', 'trip')
                        if trip_offset is not None:
                            trip_ptr = trip_desc_addr + trip_offset
                            trip_info["temperature"] = self.ramdump.read_structure_field(trip_ptr,
                                                                                        'struct thermal_trip',
                                                                                        'temperature')
                            trip_info["hysteresis"] = self.ramdump.read_structure_field(trip_ptr,
                                                                                        'struct thermal_trip',
                                                                                        'hysteresis')
                            trip_info["type"] = self.ramdump.read_structure_field(trip_ptr,
                                                                                  'struct thermal_trip',
                                                                                  'type')
                        tzone_data_dict["trips_invalid"].append(trip_info)

            user_thresholds_offset = self.ramdump.field_offset('struct thermal_zone_device', 'user_thresholds')
            if user_thresholds_offset:
                tzone_data_dict["user_thresholds_list"] = hex(tz_device_addr + user_thresholds_offset)

                # Parse user_thresholds list (kernel 6.0+)
                tzone_data_dict["user_thresholds"] = []
                user_thresholds_list_addr = tz_device_addr + user_thresholds_offset
                list_node_offset = self.ramdump.field_offset('struct user_threshold', 'list_node')
                if list_node_offset is not None:
                    threshold_walker = llist.ListWalker(self.ramdump, user_thresholds_list_addr, list_node_offset)
                    for user_threshold_addr in threshold_walker:
                        threshold_info = {}
                        threshold_info["address"] = hex(user_threshold_addr)
                        threshold_info["temperature"] = self.ramdump.read_structure_field(user_threshold_addr,
                                                                                          'struct user_threshold',
                                                                                          'temperature')
                        threshold_info["direction"] = self.ramdump.read_structure_field(user_threshold_addr,
                                                                                        'struct user_threshold',
                                                                                        'direction')
                        tzone_data_dict["user_thresholds"].append(threshold_info)

            # Parse thermal instances - architecture changed in kernel 6.0+
            tzone_data_dict["trips_data"] = trips_data = {}
            trip_triggered = False
            kv = self.ramdump.kernel_version

            # Check if thermal_instances field exists (older kernels < 6.0)
            thermal_instances_offset = self.ramdump.field_offset('struct thermal_zone_device', 'thermal_instances')

            if thermal_instances_offset:
                # Old architecture: thermal_instances list at zone level (kernels < 6.0)
                node_addr = self.ramdump.struct_field_addr(tz_device_addr,
                                                           "struct thermal_zone_device",
                                                           "thermal_instances")
                # Try new list node name first (trip_node), fallback to old name (tz_node)
                list_offset = self.ramdump.field_offset('struct thermal_instance', 'trip_node')
                if not list_offset:
                    list_offset = self.ramdump.field_offset('struct thermal_instance', 'tz_node')

                device_list_walker = llist.ListWalker(self.ramdump, node_addr, list_offset)
                trip_number = 0

                for thermal_instance_addr in device_list_walker:
                    _trip_data = {}
                    # Read trip field from thermal_instance for all kernel versions < 6.0
                    current_trip = self.ramdump.read_structure_field(thermal_instance_addr,
                                                                     'struct thermal_instance', 'trip')
                    if current_trip is None or current_trip > THERMAL_MAX_TRIPS:
                        continue
                    if current_trip not in trips_data:
                        trips_data[current_trip] = []

                    _trip_data["id"] = self.ramdump.read_structure_field(thermal_instance_addr,
                                                                         'struct thermal_instance',
                                                                         'id')
                    instance_name_addr = self.ramdump.struct_field_addr(thermal_instance_addr,
                                                                        'struct thermal_instance', 'name')
                    _trip_data["name"] = self.ramdump.read_cstring(instance_name_addr)
                    _trip_data["initialized"] = self.ramdump.read_bool(
                        self.ramdump.struct_field_addr(thermal_instance_addr,
                                                       'struct thermal_instance', 'initialized'))
                    if _trip_data["initialized"] in [0, "0"]:
                        _trip_data["initialized"] = "False"
                    elif _trip_data["initialized"] in [1, "1"]:
                        _trip_data["initialized"] = "True"

                    _trip_data["lower"] = self.ramdump.read_structure_field(thermal_instance_addr,
                                                                            'struct thermal_instance', 'lower')
                    _trip_data["upper"] = self.ramdump.read_structure_field(thermal_instance_addr,
                                                                            'struct thermal_instance', 'upper')
                    _trip_data["target"] = self.ramdump.read_structure_field(thermal_instance_addr,
                                                                             'struct thermal_instance', 'target')
                    _trip_data["weight"] = self.ramdump.read_structure_field(thermal_instance_addr,
                                                                             'struct thermal_instance', 'weight')
                    _trip_data["upper_no_limit"] = self.ramdump.read_bool(
                        self.ramdump.struct_field_addr(thermal_instance_addr,
                                                       'struct thermal_instance', 'upper_no_limit'))
                    if _trip_data["upper_no_limit"] in [0, "0"]:
                        _trip_data["upper_no_limit"] = "False"
                    elif _trip_data["upper_no_limit"] in [1, "1"]:
                        _trip_data["upper_no_limit"] = "True"

                    if _trip_data["target"] > 0xFFFFFF:
                        _trip_data["trip_status"] = "Not Triggered"
                    elif _trip_data["target"] == 0:
                        _trip_data["trip_status"] = "In Clear State"
                    else:
                        trip_triggered = True
                        _trip_data["trip_status"] = "In Trigger State"

                    _trip_data["cdev"] = {}
                    cdev_addr = self.ramdump.read_structure_field(thermal_instance_addr,
                                                                  'struct thermal_instance', 'cdev')
                    self.parse_cooling_device_fields(cdev_addr, _trip_data["cdev"])

                    trips_data[current_trip].append(_trip_data)

                if trip_triggered:
                    triggered_zones.append(tzone_data_dict["type"])
            else:
                # Kernel 6.0+: thermal instances are stored per-trip in trips[] array
                # Each trip (thermal_trip_desc) has its own thermal_instances list
                trip_count = tzone_data_dict.get("trip_count", 0)
                if trip_count > 0:
                    # Get the trips array address
                    trips_offset = self.ramdump.field_offset('struct thermal_zone_device', 'trips')
                    if trips_offset:
                        trips_array_addr = tz_device_addr + trips_offset
                        trip_desc_size = self.ramdump.sizeof('struct thermal_trip_desc')

                        if trip_desc_size:
                            # Iterate through each trip in the trips[] array
                            for trip_idx in range(trip_count):
                                trip_desc_addr = trips_array_addr + (trip_idx * trip_desc_size)

                                # Read thermal_trip_desc fields for this trip
                                trip_desc_info = {}
                                trip_desc_info["trip_desc_addr"] = hex(trip_desc_addr)

                                # Read trip pointer (points to struct thermal_trip)
                                trip_ptr_offset = self.ramdump.field_offset('struct thermal_trip_desc', 'trip')
                                if trip_ptr_offset:
                                    trip_ptr = self.ramdump.read_pointer(trip_desc_addr + trip_ptr_offset)
                                    if trip_ptr:
                                        trip_desc_info["trip_ptr"] = hex(trip_ptr)
                                        # Read thermal_trip fields
                                        trip_desc_info["trip_temperature"] = self.ramdump.read_structure_field(trip_ptr, 'struct thermal_trip', 'temperature')
                                        trip_desc_info["trip_hysteresis"] = self.ramdump.read_structure_field(trip_ptr, 'struct thermal_trip', 'hysteresis')
                                        trip_desc_info["trip_type"] = self.ramdump.read_structure_field(trip_ptr, 'struct thermal_trip', 'type')
                                        trip_desc_info["trip_flags"] = self.ramdump.read_structure_field(trip_ptr, 'struct thermal_trip', 'flags')

                                # Read threshold field
                                threshold_offset = self.ramdump.field_offset('struct thermal_trip_desc', 'threshold')
                                if threshold_offset:
                                    trip_desc_info["threshold"] = self.ramdump.read_s32(trip_desc_addr + threshold_offset)

                                # Read trip_attrs pointer
                                trip_attrs_offset = self.ramdump.field_offset('struct thermal_trip_desc', 'trip_attrs')
                                if trip_attrs_offset:
                                    trip_attrs_ptr = self.ramdump.read_pointer(trip_desc_addr + trip_attrs_offset)
                                    if trip_attrs_ptr:
                                        trip_desc_info["trip_attrs_ptr"] = hex(trip_attrs_ptr)

                                # Store trip_desc_info in trips_data
                                if trip_idx not in trips_data:
                                    trips_data[trip_idx] = []

                                # Get the thermal_instances list for this trip
                                thermal_instances_list_offset = self.ramdump.field_offset('struct thermal_trip_desc', 'thermal_instances')
                                if thermal_instances_list_offset:
                                    trip_instances_list_addr = trip_desc_addr + thermal_instances_list_offset

                                    # Get the list node offset in thermal_instance (trip_node)
                                    trip_node_offset = self.ramdump.field_offset('struct thermal_instance', 'trip_node')
                                    if trip_node_offset:
                                        # Walk the thermal_instances list for this trip
                                        instance_walker = llist.ListWalker(self.ramdump, trip_instances_list_addr, trip_node_offset)

                                        if trip_idx not in trips_data:
                                            trips_data[trip_idx] = []

                                        # Store trip descriptor info as first element if instances exist
                                        has_instances = False
                                        for thermal_instance_addr in instance_walker:
                                            if not has_instances:
                                                # Add trip descriptor info as metadata for this trip
                                                trips_data[trip_idx].append({"trip_desc_info": trip_desc_info})
                                                has_instances = True

                                            _trip_data = {}

                                            # Read thermal_instance fields
                                            _trip_data["id"] = self.ramdump.read_structure_field(thermal_instance_addr,
                                                                                                 'struct thermal_instance', 'id')
                                            instance_name_addr = self.ramdump.struct_field_addr(thermal_instance_addr,
                                                                                                'struct thermal_instance', 'name')
                                            _trip_data["name"] = self.ramdump.read_cstring(instance_name_addr)
                                            _trip_data["initialized"] = self.ramdump.read_bool(
                                                self.ramdump.struct_field_addr(thermal_instance_addr,
                                                                               'struct thermal_instance', 'initialized'))
                                            if _trip_data["initialized"] in [0, "0"]:
                                                _trip_data["initialized"] = "False"
                                            elif _trip_data["initialized"] in [1, "1"]:
                                                _trip_data["initialized"] = "True"

                                            _trip_data["lower"] = self.ramdump.read_structure_field(thermal_instance_addr,
                                                                                                    'struct thermal_instance', 'lower')
                                            _trip_data["upper"] = self.ramdump.read_structure_field(thermal_instance_addr,
                                                                                                    'struct thermal_instance', 'upper')
                                            _trip_data["target"] = self.ramdump.read_structure_field(thermal_instance_addr,
                                                                                                     'struct thermal_instance', 'target')
                                            _trip_data["weight"] = self.ramdump.read_structure_field(thermal_instance_addr,
                                                                                                     'struct thermal_instance', 'weight')
                                            _trip_data["upper_no_limit"] = self.ramdump.read_bool(
                                                self.ramdump.struct_field_addr(thermal_instance_addr,
                                                                               'struct thermal_instance', 'upper_no_limit'))
                                            if _trip_data["upper_no_limit"] in [0, "0"]:
                                                _trip_data["upper_no_limit"] = "False"
                                            elif _trip_data["upper_no_limit"] in [1, "1"]:
                                                _trip_data["upper_no_limit"] = "True"

                                            if _trip_data["target"] > 0xFFFFFF:
                                                _trip_data["trip_status"] = "Not Triggered"
                                            elif _trip_data["target"] == 0:
                                                _trip_data["trip_status"] = "In Clear State"
                                            else:
                                                trip_triggered = True
                                                _trip_data["trip_status"] = "In Trigger State"

                                            # Get the cooling device
                                            _trip_data["cdev"] = {}
                                            cdev_addr = self.ramdump.read_structure_field(thermal_instance_addr,
                                                                                          'struct thermal_instance', 'cdev')
                                            self.parse_cooling_device_fields(cdev_addr, _trip_data["cdev"])

                                            trips_data[trip_idx].append(_trip_data)

                            if trip_triggered:
                                triggered_zones.append(tzone_data_dict["type"])
                        else:
                            tzone_data_dict["trips_data_note"] = "Could not determine thermal_trip_desc size"
                    else:
                        tzone_data_dict["trips_data_note"] = "Could not find trips array offset"
                else:
                    tzone_data_dict["trips_data_note"] = "No trips defined for this zone"

        except Exception as e:
            tzone_data_dict["exception"] = str(e)
            print_out_str(traceback.format_exc())

        if tzone_data_dict and tzone_id is not None:
            thermal_tzone_dict.append(tzone_data_dict)
        return

    def parse_thremal_zone_data(self, dump):
        self.tzone_struct_list = []
        self.triggered_zones = []

        # thermal_zone data
        thermal_tz_list = self.ramdump.address_of('thermal_tz_list')
        list_offset = self.ramdump.field_offset('struct thermal_zone_device', 'node')
        list_walker = llist.ListWalker(self.ramdump, thermal_tz_list, list_offset)
        list_walker.walk(self.parse_thermal_zone_fields,
                         self.tzone_struct_list, self.triggered_zones)
        if len(self.tzone_struct_list) == 0:
            self.writeln("No thermal Zones defined")
            return

        self.writeln("")
        self.writeln("# Total Tzones: {0}".format(len(self.tzone_struct_list)))
        self.writeln("# violated Tzones: {0}".format(",".join(self.triggered_zones)))
        self.writeln("")
        format_str = "{0:<35} {1}"
        # Sort by temperature, handling None values
        self.tzone_struct_list.sort(key=lambda x: float(x["temperature"]) if x.get("temperature") is not None else float('-inf'), reverse=True)
        for tzone_struct in self.tzone_struct_list:
            self.writeln("")
            self.writeln("[THERMAL_ZONE_{0}]".format(tzone_struct["tzone_id"]))
            self.writeln(format_str.format("sensor", tzone_struct.get("type")))
            self.writeln(format_str.format("algo_type", tzone_struct.get("algo_type")))
            if "exception" in tzone_struct.keys():
                self.writeln(format_str.format("Exception", tzone_struct.get("exception")))
                continue

            self.writeln(format_str.format("mode", "enabled" if (tzone_struct.get("mode") == 1) else "disabled"))
            self.writeln(format_str.format("polling_delay", tzone_struct.get("polling_delay")))
            self.writeln(format_str.format("passive_delay", tzone_struct.get("passive_delay")))

            # Print temperature fields if available
            if tzone_struct.get("temperature") is not None:
                self.writeln(format_str.format("temperature", tzone_struct.get("temperature")))
            if tzone_struct.get("last_temperature") is not None:
                self.writeln(format_str.format("last_temperature", tzone_struct.get("last_temperature")))
            if tzone_struct.get("emul_temperature") is not None:
                self.writeln(format_str.format("emul_temperature", tzone_struct.get("emul_temperature")))
            if tzone_struct.get("prev_high_trip") is not None:
                self.writeln(format_str.format("prev_high_trip", tzone_struct.get("prev_high_trip")))
            if tzone_struct.get("prev_low_trip") is not None:
                self.writeln(format_str.format("prev_low_trip", tzone_struct.get("prev_low_trip")))
            if tzone_struct.get("passive") is not None:
                self.writeln(format_str.format("passive", tzone_struct.get("passive")))

            # Print new fields if available (kernel 6.0+)
            if tzone_struct.get("recheck_delay_jiffies") is not None:
                self.writeln(format_str.format("recheck_delay_jiffies", tzone_struct.get("recheck_delay_jiffies")))
            if tzone_struct.get("notify_event") is not None:
                self.writeln(format_str.format("notify_event", tzone_struct.get("notify_event")))
            if tzone_struct.get("state") is not None:
                self.writeln(format_str.format("state", tzone_struct.get("state")))

            # Print legacy fields if available (removed in kernel 6.0+)
            if tzone_struct.get("need_update") is not None:
                self.writeln(format_str.format("tzone_registered", tzone_struct.get("need_update")))
            if tzone_struct.get("suspended") is not None:
                self.writeln(format_str.format("suspended", tzone_struct.get("suspended")))

            self.writeln(format_str.format("trip_count", tzone_struct.get("trip_count")))
            if tzone_struct.get("trips_disabled") is not None:
                self.writeln(format_str.format("trips_disabled", tzone_struct.get("trips_disabled")))

            # Print note if trip instance parsing is not supported for this kernel
            if tzone_struct.get("trips_data_note") is not None:
                self.writeln(format_str.format("trips_data_note", tzone_struct.get("trips_data_note")))

            self.writeln(format_str.format("tzone_data_struct",
                                           "v.v ((struct thermal_zone_device *){0}".format(
                                               tzone_struct.get("tz_device_addr"))))
            self.writeln(format_str.format("tzone devdata ",
                                           "v.v ((struct __thermal_zone *){0}".format(
                                               tzone_struct.get("devdata"))))

            # Print kernel 6.0+ list head pointers if available
            if tzone_struct.get("trips_high_list"):
                self.writeln(format_str.format("trips_high_list",
                                               "v.v ((struct list_head *){0})".format(tzone_struct.get("trips_high_list"))))
            if tzone_struct.get("trips_reached_list"):
                self.writeln(format_str.format("trips_reached_list",
                                               "v.v ((struct list_head *){0})".format(tzone_struct.get("trips_reached_list"))))
            if tzone_struct.get("trips_invalid_list"):
                self.writeln(format_str.format("trips_invalid_list",
                                               "v.v ((struct list_head *){0})".format(tzone_struct.get("trips_invalid_list"))))
            if tzone_struct.get("user_thresholds_list"):
                self.writeln(format_str.format("user_thresholds_list",
                                               "v.v ((struct list_head *){0})".format(tzone_struct.get("user_thresholds_list"))))

            # Print trips_high list if available (kernel 6.0+)
            trips_high = tzone_struct.get("trips_high")
            if trips_high:
                self.writeln("")
                self.writeln("Trips High ({0} total):".format(len(trips_high)))
                for idx, trip in enumerate(trips_high):
                    self.writeln("  Trip {0}:".format(idx))
                    self.writeln("\t {0:<35} {1}".format("trip_desc_addr",
                                                         "v.v ((struct thermal_trip_desc *){0})".format(trip.get("trip_desc_addr"))))
                    if trip.get("temperature") is not None:
                        self.writeln("\t {0:<35} {1}".format("temperature", trip.get("temperature")))
                    if trip.get("hysteresis") is not None:
                        self.writeln("\t {0:<35} {1}".format("hysteresis", trip.get("hysteresis")))
                    if trip.get("type") is not None:
                        self.writeln("\t {0:<35} {1}".format("type", trip.get("type")))
                    if trip.get("threshold") is not None:
                        self.writeln("\t {0:<35} {1}".format("threshold", trip.get("threshold")))

            # Print trips_reached list if available (kernel 6.0+)
            trips_reached = tzone_struct.get("trips_reached")
            if trips_reached:
                self.writeln("")
                self.writeln("Trips Reached ({0} total):".format(len(trips_reached)))
                for idx, trip in enumerate(trips_reached):
                    self.writeln("  Trip {0}:".format(idx))
                    self.writeln("\t {0:<35} {1}".format("trip_desc_addr",
                                                         "v.v ((struct thermal_trip_desc *){0})".format(trip.get("trip_desc_addr"))))
                    if trip.get("temperature") is not None:
                        self.writeln("\t {0:<35} {1}".format("temperature", trip.get("temperature")))
                    if trip.get("hysteresis") is not None:
                        self.writeln("\t {0:<35} {1}".format("hysteresis", trip.get("hysteresis")))
                    if trip.get("type") is not None:
                        self.writeln("\t {0:<35} {1}".format("type", trip.get("type")))
                    if trip.get("threshold") is not None:
                        self.writeln("\t {0:<35} {1}".format("threshold", trip.get("threshold")))

            # Print trips_invalid list if available (kernel 6.0+)
            trips_invalid = tzone_struct.get("trips_invalid")
            if trips_invalid:
                self.writeln("")
                self.writeln("Trips Invalid ({0} total):".format(len(trips_invalid)))
                for idx, trip in enumerate(trips_invalid):
                    self.writeln("  Trip {0}:".format(idx))
                    self.writeln("\t {0:<35} {1}".format("trip_desc_addr",
                                                         "v.v ((struct thermal_trip_desc *){0})".format(trip.get("trip_desc_addr"))))
                    if trip.get("temperature") is not None:
                        self.writeln("\t {0:<35} {1}".format("temperature", trip.get("temperature")))
                    if trip.get("hysteresis") is not None:
                        self.writeln("\t {0:<35} {1}".format("hysteresis", trip.get("hysteresis")))
                    if trip.get("type") is not None:
                        self.writeln("\t {0:<35} {1}".format("type", trip.get("type")))
                    if trip.get("threshold") is not None:
                        self.writeln("\t {0:<35} {1}".format("threshold", trip.get("threshold")))

            # Print user thresholds if available (kernel 6.0+)
            user_thresholds = tzone_struct.get("user_thresholds")
            if user_thresholds:
                self.writeln("")
                self.writeln("User Thresholds ({0} total):".format(len(user_thresholds)))
                for idx, threshold in enumerate(user_thresholds):
                    self.writeln("  Threshold {0}:".format(idx))
                    self.writeln("\t {0:<35} {1}".format("address",
                                                         "v.v ((struct user_threshold *){0})".format(threshold.get("address"))))
                    self.writeln("\t {0:<35} {1}".format("temperature", threshold.get("temperature")))
                    direction = threshold.get("direction")
                    direction_str = "UNKNOWN"
                    if direction == 0:
                        direction_str = "FALLING (0)"
                    elif direction == 1:
                        direction_str = "RISING (1)"
                    self.writeln("\t {0:<35} {1}".format("direction", direction_str))

            # print trip data
            self.writeln("Devices:")
            cdev_format_str = "\t\t{0:<35} {1}"
            trips_data = tzone_struct.get("trips_data")
            if not trips_data:
                self.writeln("\tNo Cooling Devices")
                continue
            trip_nums = sorted(trips_data.keys())
            for trip_num in trip_nums:
                trip_cdevs_info = trips_data[trip_num]
                self.writeln("  Trip{0}:".format(trip_num))

                # Check if first element contains trip descriptor info (kernel 6.0+)
                if trip_cdevs_info and "trip_desc_info" in trip_cdevs_info[0]:
                    trip_desc = trip_cdevs_info[0]["trip_desc_info"]
                    self.writeln("\t {0:<35} {1}".format("trip_desc_addr",
                                                         "v.v ((struct thermal_trip_desc *){0})".format(trip_desc.get("trip_desc_addr"))))
                    if trip_desc.get("trip_ptr"):
                        self.writeln("\t {0:<35} {1}".format("trip_ptr",
                                                             "v.v ((struct thermal_trip *){0})".format(trip_desc.get("trip_ptr"))))
                    if trip_desc.get("trip_temperature") is not None:
                        self.writeln("\t {0:<35} {1}".format("trip_temperature", trip_desc.get("trip_temperature")))
                    if trip_desc.get("trip_hysteresis") is not None:
                        self.writeln("\t {0:<35} {1}".format("trip_hysteresis", trip_desc.get("trip_hysteresis")))
                    if trip_desc.get("trip_type") is not None:
                        self.writeln("\t {0:<35} {1}".format("trip_type", trip_desc.get("trip_type")))
                    if trip_desc.get("trip_flags") is not None:
                        self.writeln("\t {0:<35} {1}".format("trip_flags", trip_desc.get("trip_flags")))
                    if trip_desc.get("threshold") is not None:
                        self.writeln("\t {0:<35} {1}".format("threshold", trip_desc.get("threshold")))
                    if trip_desc.get("trip_attrs_ptr"):
                        self.writeln("\t {0:<35} {1}".format("trip_attrs_ptr",
                                                             "v.v ((struct thermal_trip_attrs *){0})".format(trip_desc.get("trip_attrs_ptr"))))
                    # Skip the first element when iterating cooling devices
                    trip_cdevs_info = trip_cdevs_info[1:]

                for trip_info in trip_cdevs_info:
                    if trip_info.get("trip_status") is not None:
                        self.writeln("\t {0:<35} {1}".format("trip_status", trip_info.get("trip_status")))

                    cdev_dict = trip_info.get("cdev")
                    if not cdev_dict or len(cdev_dict) != 1:
                        self.writeln("Invalid cdev for trip instance")
                        continue
                    cdev_id = list(cdev_dict.keys())[0]
                    cdev_dict = cdev_dict[cdev_id]
                    self.writeln("\t {0}".format(cdev_dict.get("cdev_type")))
                    self.writeln(cdev_format_str.format("id", cdev_id))
                    self.writeln(cdev_format_str.format("initialized", trip_info.get("initialized")))
                    if trip_info.get("upper_no_limit") is not None:
                        self.writeln(cdev_format_str.format("upper_no_limit", trip_info.get("upper_no_limit")))
                    if trip_info.get("weight"):
                        self.writeln(cdev_format_str.format("weight", trip_info.get("weight")))
                    self.writeln(cdev_format_str.format("states(lower, upper, cur_state)",
                                                        "({0}, {1}, {2})".format(
                                                            trip_info.get("lower"),
                                                            trip_info.get("upper"),
                                                            trip_info.get("target"))))

                    stats_data = cdev_dict.get("stats_addr")
                    stats_state = "NA"
                    if stats_data:
                        stats_state = cdev_dict.get("stats_state")
                    self.writeln(cdev_format_str.format("cdev status(updated, stats_state)",
                                                        "({0}, {1})".format(cdev_dict.get("updated"), stats_state)))
                    if stats_data:
                        self.writeln(cdev_format_str.format("stats_total_trans",
                                                            cdev_dict.get("stats_total_trans")))
                        last_time = cdev_dict.get("stats_last_time")
                        self.writeln(cdev_format_str.format("stats_last_time",
                                                            hex(last_time) if last_time is not None else "N/A"))
                    self.writeln("")

        return

    def parse_cooling_device_data(self, dump):
        self.cdev_struct_list = {}
        # thermal_zone data
        thermal_cdev_list = self.ramdump.address_of('thermal_cdev_list')
        list_offset = self.ramdump.field_offset('struct thermal_cooling_device', 'node')
        list_walker = llist.ListWalker(self.ramdump, thermal_cdev_list, list_offset)
        list_walker.walk(self.parse_cooling_device_fields, self.cdev_struct_list)
        cdev_ids_list = self.cdev_struct_list.keys()
        if not cdev_ids_list:
            print_out_str("No cooling Devices or exception in parsing")
            return

        format_str = "{0:<35} {1}"
        cdev_ids_list = sorted(cdev_ids_list)
        for cdev_id in cdev_ids_list:
            cdev_struct = self.cdev_struct_list[cdev_id]
            self.writeln("")
            self.writeln("[COOLING_DEVICE_{0}]".format(cdev_id))
            self.writeln(format_str.format("type", cdev_struct.get("cdev_type")))
            self.writeln(format_str.format("updated", cdev_struct.get("updated")))
            stats_addr = cdev_struct.get("stats_addr")
            if stats_addr:
                self.writeln(format_str.format("state", cdev_struct.get("stats_state")))
                self.writeln(format_str.format("total_trans", cdev_struct.get("stats_total_trans")))
                last_time = cdev_struct.get("stats_last_time")
                self.writeln(format_str.format("last_time", hex(last_time) if last_time is not None else "N/A"))

            # Print max_state if available
            if cdev_struct.get("max_state") is not None:
                self.writeln(format_str.format("cdev_max_state", cdev_struct.get("max_state")))

            self.writeln(format_str.format("cdev_struct",
                                           "v.v (struct thermal_cooling_device*){0}".format(
                                               hex(cdev_struct.get("cdev_struct_addr")))))
            self.writeln(format_str.format("cdev_devdata",
                                           "v.v (struct *){0}".format(hex(cdev_struct.get("devdata")))))
            self.writeln(format_str.format("cdev_stats_struct",
                                           "v.v (struct cooling_dev_stats*){0}".format(
                                               hex(stats_addr) if stats_addr else "N/A")))

            if "exception" in cdev_struct.keys():
                self.writeln(format_str.format("Exception", cdev_struct.get("exception")))

        return

    def parse_tsen_device_data(self, dump):
        tsens_device_list = self.ramdump.address_of('tsens_device_list')
        list_offset = self.ramdump.field_offset('struct tsens_device', 'list')
        list_walker = llist.ListWalker(self.ramdump, tsens_device_list, list_offset)
        list_walker.walk(self.tsens_dbg_parse_fields)

    def write(self, string):
        self.out.write(string)

    def writeln(self, string=""):
        self.out.write(string + '\n')

    def parse(self):
        print_out_str("Started thermal parsing")
        kv = self.ramdump.kernel_version
        if (kv[0], kv[1]) == (5, 4):
            self.parser_list = self.parser_list_5_4
        elif (kv[0], kv[1]) > (5, 4):
            self.parser_list = self.parser_list_5_10
        else:
            self.parser_list = self.parser_list_v1

        for subparser in self.parser_list:
            try:
                self.out = self.ramdump.open_file('thermal_info/' + subparser[2], subparser[3])
                self.write(subparser[1].center(90, '-') + '\n')
                subparser[0](self.ramdump)
                self.writeln()
                self.out.close()
            except Exception as e:
                if self.out:
                    self.writeln(str(e))
                    self.out.close()
                print_out_str("Thermal info: Parsing failed in "
                              + subparser[0].__name__)
                print_out_str(traceback.format_exc())
        print_out_str("Done thermal parsing")
