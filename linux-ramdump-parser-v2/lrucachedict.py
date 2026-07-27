# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: GPL-2.0-only

from collections import OrderedDict
from print_out import print_out_str

class LRUCacheDict:
    def __init__(self, max_bytes, cache_size=4096, evict_percent=1, large_size_percent=5):
        self.cache = OrderedDict()
        self.max_bytes = max_bytes
        self.cache_size = cache_size
        self.current_bytes = 0
        self.put_counter = 0
        self.stats = {'hit':0, 'miss':0, 'evict':0}
        self.evict_percent = evict_percent
        self.large_size_percent = large_size_percent
        self.set_large_size(self.large_size_percent)
        self.set_evict_interval(self.evict_percent)

    def get(self, key):
        if key in self.cache:
            self.stats['hit'] += 1
            self.cache.move_to_end(key)
            return self.cache[key]
        self.stats['miss'] += 1
        return None

    def put(self, key, value):
        value_size = len(value)
        if key in self.cache:
            old_size = len(self.cache[key])
            self.current_bytes -= old_size
            self.cache.move_to_end(key)
        self.cache[key] = value
        self.current_bytes += value_size

        self.put_counter += 1
        if self.put_counter >= self.evict_interval:
            self.evict_if_needed()
            self.put_counter = 0

    def set_max_bytes(self, new_max_bytes):
        self.max_bytes = new_max_bytes
        self.set_evict_interval(self.evict_percent)
        self.evict_if_needed()

    def set_cache_size(self, new_cache_size):
        self.cache_size = new_cache_size
        self.set_evict_interval(self.evict_percent)
        self.cache.clear()
        self.current_bytes = 0

    def set_large_size(self, large_data_percent):
        self.large_size = (self.max_bytes * large_data_percent) // 100

    def set_evict_interval(self, evict_percent, min_interval=50, max_interval=5000):
        total_pages = self.max_bytes // self.cache_size
        interval = total_pages * evict_percent // 100
        self.evict_interval = max(min_interval, min(interval, max_interval))

    def evict_if_needed(self):
        while self.current_bytes > self.max_bytes:
            old_key, old_value = self.cache.popitem(last=False)
            self.current_bytes -= len(old_value)
            self.stats['evict'] += 1

    def print_stats(self, cache_name):
        print_out_str(
            "[{}] {:,} / {:,} bytes | hit={}, miss={}, evict={}".format(
                cache_name,
                self.current_bytes, self.max_bytes,
                self.stats['hit'], self.stats['miss'], self.stats['evict']
            )
        )