# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: GPL-2.0-only

"""Common helpers for display parsers."""


class PacAwareRamDump(object):
    """Expose normalized kernel pointers without changing global parser APIs.

    ``read_pointer`` intentionally returns the raw value in RamDump.  Display
    structures are frequently heap allocated and their pointers can carry PAC
    or HW-tag bits, so callers in this package must canonicalize them before
    using them as virtual addresses.
    """

    def __init__(self, ramdump):
        self._ramdump = ramdump

    def read_pointer(self, *args, **kwargs):
        return self._ramdump.pac_ignore(
            self._ramdump.read_pointer(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._ramdump, name)
