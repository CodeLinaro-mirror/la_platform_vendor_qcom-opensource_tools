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

# Global Configurations
ADRENO_DISPATCH_DRAWQUEUE_SIZE = 128
KGSL_DEVMEMSTORE_SIZE = 40
KGSL_PRIORITY_MAX_RB_LEVELS = 4
KGSL_MAX_POOLS = 6
PAGE_SIZE = 4096

KGSL_CACHEMODE_MASK = 0x0C000000
KGSL_CACHEMODE_SHIFT = 26
KGSL_MEMALIGN_MASK = 0x00FF0000
KGSL_MEMALIGN_SHIFT = 16
KGSL_MEMTYPE_MASK = 0x0000FF00
KGSL_MEMTYPE_SHIFT = 8

KGSL_CONTEXT_SECURE = 0x00020000

KGSL_MEMDESC_GLOBAL = (1 << 1)
KGSL_MEMDESC_SECURE = (1 << 4)
KGSL_MEMDESC_PRIVILEGED = (1 << 6)
KGSL_MEMDESC_UCODE = (1 << 7)
KGSL_MEMDESC_RANDOM = (1 << 8)

KGSL_MEMFLAGS_GPUREADONLY = (1 << 24)
KGSL_MEMFLAGS_USE_CPU_MAP = (1 << 28)
KGSL_MEMFLAGS_VBO = (1 << 34)

VRB_PREEMPT_COUNT_TOTAL_L0_IDX = 6
VRB_PREEMPT_COUNT_TOTAL_L1A_IDX = 7
VRB_PREEMPT_COUNT_TOTAL_L1B_IDX = 8

KGSL_HFI_MEMKIND_SCRATCH = 0x2

MAX_NUM_GC_RBS = 4
MAX_NUM_LPAC_RBS = 1
MAX_NUM_RBS = (MAX_NUM_GC_RBS + MAX_NUM_LPAC_RBS)
RB_SCRATCH_DWORDS_SZ = 5

kgsl_cachemode = ['-', 'u', 't', 'b']

kgsl_ctx_type = ['ANY', 'GL', 'CL', 'C2D', 'RS', 'VK']

pwrctrl_data = ['active_pwrlevel', 'previous_pwrlevel', 'default_pwrlevel',
                'thermal_pwrlevel', 'thermal_time', 'power_flags',
                'ctrl_flags', 'rt_bus_hint', 'num_pwrlevels',
                'min_pwrlevel', 'max_pwrlevel', 'bus_percent_ab',
                'bus_width', 'bus_ab_mbytes', 'cur_buslevel']

adreno_boolean_data = ['long_ib_detect', 'lm_enabled', 'acd_enabled',
                        'hwcg_enabled', 'throttling_enabled',
                        'sptp_pc_enabled', 'bcl_enabled', 'clx_enabled',
                        'dms_enabled', 'gmu_ab', 'gpu_llc_slice_enable',
                        'gpuhtw_llc_slice_enable', 'lpac_enabled',
                        'perfcounter', ]

hwsched_flags_data = ['ADRENO_HWSCHED_POWER', 'ADRENO_HWSCHED_ACTIVE',
                      'ADRENO_HWSCHED_CTX_BAD_LEGACY',
                      'ADRENO_HWSCHED_CONTEXT_QUEUE',
                      'ADRENO_HWSCHED_HW_FENCE',
                      'ADRENO_HWSCHED_FORCE_RETIRE_GMU',
                      'ADRENO_HWSCHED_GPU_SOFT_RESET', ]

DCVS_Tunables_list = ['penalty_up', 'penalty_down', 'first_step_down',
                      'subsequent_step_down', 'min_freq_mhz', 'max_freq_mhz',
                      'target_fps', 'num_samples_up', 'num_samples_down',
                      'strict_frame', 'non_linear_ramp_up',
                      'non_linear_ramp_down', 'mod_percent', 'bus_min_freq',
                      'bus_max_freq', 'min_ab_mbps', 'max_ab_mbps', ]


kgsl_ctx_priv = [
    ((1 << 0), 's', 'submitted'),           # KGSL_CONTEXT_PRIV_SUBMITTED
    ((1 << 1), 'd', 'detached'),            # KGSL_CONTEXT_PRIV_DETACHED
    ((1 << 2), 'i', 'invalid'),             # KGSL_CONTEXT_PRIV_INVALID
    ((1 << 3), 'p', 'pagefault'),           # KGSL_CONTEXT_PRIV_PAGEFAULT
    ((1 << 16), 'F', 'Fault'),              # ADRENO_CONTEXT_FAULT
    ((1 << 17), 'H', 'GPU Hang'),           # ADRENO_CONTEXT_GPU_HANG
    ((1 << 18), 'T', 'GPU Hang FT'),        # ADRENO_CONTEXT_GPU_HANG_FT
    ((1 << 19), 'E', 'Skip EOF'),           # ADRENO_CONTEXT_SKIP_EOF
    ((1 << 20), 'P', 'Force Preamble'),     # ADRENO_CONTEXT_FORCE_PREAMBLE
    ((1 << 21), 'C', 'Skip CMD'),           # ADRENO_CONTEXT_SKIP_CMD
    ((1 << 22), 'L', 'Fence Log')           # ADRENO_CONTEXT_FENCE_LOG
]

kgsl_memtype = [
                'any(0)',
                'framebuffer',
                'renderbuffer',
                'arraybuffer',
                'elementarraybuffer',
                'vertexarraybuffer',
                'texture',
                'surface',
                'egl_surface',
                'gl',
                'cl',
                'cl_buffer_map',
                'cl_buffer_nomap',
                'cl_image_map',
                'cl_image_nomap',
                'cl_kernel_stack',
                'command',
                '2d',
                'egl_image',
                'egl_shadow',
                'egl_multisample',
                'kernel'
]

adreno_preempt_state = ['NONE', 'START', 'TRIGGERED', 'FAULTED', 'PENDING',
                        'COMPLETE']


def strhex(x): return str(hex(x))
def str_convert_to_kb(x): return str(x//1024) + 'kb'


def parse_memstore_memory_common(dump, hostptr, size, writeln):
    preempted = dump.read_s32(hostptr + 16)
    current_context = dump.read_s32(hostptr + 32)

    writeln("hostptr: " + strhex(hostptr))
    writeln("current_context: " + str(current_context))
    writeln("preempted: " + str(preempted) + " [Deprecated]")

    def add_increment(x): return x + 4

    writeln("\nrb contexts:")
    format_str = '{0:^20} {1:^20} {2:^20} {3:^20}'
    writeln(format_str.format("rb_index", "soptimestamp",
                              "eoptimestamp", "current_context"))

    # Skip process contexts since their timestamps are
    # displayed in open/active context sections
    hostptr = hostptr + size - (5 * KGSL_DEVMEMSTORE_SIZE) - 8
    for rb_id in range(KGSL_PRIORITY_MAX_RB_LEVELS):
        soptimestamp = dump.read_s32(hostptr)
        hostptr = add_increment(hostptr)
        # skip unused entry
        hostptr = add_increment(hostptr)
        eoptimestamp = dump.read_s32(hostptr)
        hostptr = add_increment(hostptr)
        # skip unused entry
        hostptr = add_increment(hostptr)
        # skip preempted entry
        hostptr = add_increment(hostptr)
        # skip unused entry
        hostptr = add_increment(hostptr)
        # skip ref_wait_ts entry
        hostptr = add_increment(hostptr)
        # skip unused entry
        hostptr = add_increment(hostptr)
        current_context = dump.read_s32(hostptr)
        hostptr = add_increment(hostptr)
        # skip unused entry
        hostptr = add_increment(hostptr)

        writeln(format_str.format(str(rb_id), str(soptimestamp),
                                  str(eoptimestamp), current_context))
