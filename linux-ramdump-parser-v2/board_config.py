# SPDX-License-Identifier: GPL-2.0-only
# Copyright (c) 2024 Qualcomm Innovation Center, Inc. All rights reserved.


from boards import Board

class BoardQCM6490(Board):
    def __init__(self, socid):
        super(BoardQCM6490, self).__init__()
        self.socid = socid
        self.board_num = "qcm6490"
        self.cpu = 'CORTEXA53'
        self.ram_start = 0x80000000
        self.smem_addr = 0x900000
        self.smem_addr_buildinfo = 0x9071c0
        self.phys_offset = 0xA0000000
        self.imem_start = 0x14680000
        self.kaslr_addr = 0x146aa6d0
        self.wdog_addr = 0x146aa658
        self.imem_file_name = 'OCIMEM.BIN'
        self.arm_smmu_v12 = True

class BoardQCM6490SVM(Board):
    def __init__(self, socid):
        super(BoardQCM6490SVM, self).__init__()
        self.socid = socid
        self.board_num = "qcm6490svm"
        self.cpu = 'CORTEXA53'
        self.ram_start = 0x80000000
        self.smem_addr = 0x900000
        self.smem_addr_buildinfo = 0x9071c0
        self.phys_offset = 0xD0780000
        self.imem_start = 0x14680000
        self.kaslr_addr = 0x146aa6d0
        self.wdog_addr = 0x146aa658
        self.imem_file_name = 'OCIMEM.BIN'
        self.arm_smmu_v12 = True

class BoardQCS9100(Board):
    def __init__(self, socid):
        super(BoardQCS9100, self).__init__()
        self.socid = socid
        self.board_num = "qcs9100"
        self.cpu = 'CORTEXA53'
        self.ram_start = 0x80000000
        self.smem_addr = 0x900000
        self.smem_addr_buildinfo = 0x9071c0
        self.phys_offset = 0xA0000000
        self.imem_start = 0x14680000
        self.kaslr_addr = 0x146aa6d0
        self.wdog_addr = 0x146aa658
        self.imem_file_name = 'OCIMEM.BIN'
        self.arm_smmu_v12 = True

class BoardQCS9100SVM(Board):
    def __init__(self, socid):
        super(BoardQCS9100SVM, self).__init__()
        self.socid = socid
        self.board_num = "qcs9100svm"
        self.cpu = 'CORTEXA53'
        self.ram_start = 0x80000000
        self.smem_addr = 0x900000
        self.smem_addr_buildinfo = 0x9071c0
        self.phys_offset = 0xD0780000
        self.imem_start = 0x14680000
        self.kaslr_addr = 0x146aa6d0
        self.wdog_addr = 0x146aa658
        self.imem_file_name = 'OCIMEM.BIN'
        self.arm_smmu_v12 = True

class BoardQCS8300(Board):
    def __init__(self, socid):
        super(BoardQCS8300, self).__init__()
        self.socid = socid
        self.board_num = "qcs8300"
        self.cpu = 'CORTEXA53'
        self.ram_start = 0x80000000
        self.smem_addr = 0x900000
        self.smem_addr_buildinfo = 0x9071c0
        self.phys_offset = 0xA0000000
        self.imem_start = 0x14680000
        self.kaslr_addr = 0x146aa6d0
        self.wdog_addr = 0x146aa658
        self.imem_file_name = 'OCIMEM.BIN'
        self.arm_smmu_v12 = True

class BoardQCS8300SVM(Board):
    def __init__(self, socid):
        super(BoardQCS8300SVM, self).__init__()
        self.socid = socid
        self.board_num = "qcs8300svm"
        self.cpu = 'CORTEXA53'
        self.ram_start = 0x80000000
        self.smem_addr = 0x900000
        self.smem_addr_buildinfo = 0x9071c0
        self.phys_offset = 0xD0780000
        self.imem_start = 0x14680000
        self.kaslr_addr = 0x146aa6d0
        self.wdog_addr = 0x146aa658
        self.imem_file_name = 'OCIMEM.BIN'
        self.arm_smmu_v12 = True

class BoardQCS615(Board):
    def __init__(self, socid):
        super(BoardQCS615, self).__init__()
        self.socid = socid
        self.board_num = "qcs615"
        self.cpu = 'CORTEXA53'
        self.ram_start = 0x80000000
        self.smem_addr = 0x6000000
        self.smem_addr_buildinfo = 0x6007210
        self.phys_offset = 0x80000000
        self.imem_start = 0x14680000
        self.kaslr_addr = 0x146aa6d0
        self.wdog_addr = 0x146aa658
        self.imem_file_name = 'OCIMEM.BIN'

class BoardHamoa(Board):
    def __init__(self, socid):
        super(BoardHamoa, self).__init__()
        self.socid = socid
        self.board_num = "hamoa"
        self.cpu = 'ARMv9-A'
        self.ram_start = 0x80000000
        self.smem_addr = 0x7FE00000
        self.smem_addr_buildinfo = 0x7FE09c98
        self.phys_offset = 0xA8000000
        self.imem_start = 0x14680000
        self.kaslr_addr = 0x146aa6d0
        self.wdog_addr = 0x146aa658
        self.imem_file_name = 'OCIMEM.BIN'
        self.arm_smmu_v12 = True

class BoardKaanapali(Board):
    def __init__(self, socid):
        super(BoardKaanapali, self).__init__()
        self.socid = socid
        self.board_num = "kaanapali"
        self.cpu = 'ARMV9-A'
        self.ram_start = 0x80000000
        self.smem_addr = 0x1D00000
        self.smem_addr_buildinfo = 0x1D0A5B8
        self.phys_offset = 0xC7800000
        self.imem_start = 0x14680000
        self.kaslr_addr = 0x146806d0
        self.imem_file_name = 'OCIMEM.BIN'
        self.arm_smmu_v12 = True

class BoardSM8750(Board):
    def __init__(self, socid):
        super(BoardSM8750, self).__init__()
        self.socid = socid
        self.board_num = "sm8750"
        self.cpu = 'ARMV9-A'
        self.ram_start = 0x80000000
        self.smem_addr = 0x1D00000
        self.smem_addr_buildinfo = 0x1D08408
        self.phys_offset = 0xA8000000
        self.imem_start = 0x14680000
        self.kaslr_addr = 0x146806d0
        self.imem_offset_memdump_table = 0x10
        self.imem_file_name = 'OCIMEM.BIN'
        self.tbi_mask = 0x4000000000
        self.aff_shift = [0,0,3,0]
        self.core_map = {8:6,9:7}

class BoardSM8750SVM(Board):
    def __init__(self, socid):
        super(BoardSM8750SVM, self).__init__()
        self.socid = socid
        self.board_num = "sm8750svm"
        self.cpu = 'ARMV9-A'
        self.ram_start = 0x80000000
        self.smem_addr = 0x1D00000
        self.smem_addr_buildinfo = 0x1D08408
        self.phys_offset = 0xf3800000
        self.imem_start = 0x14680000
        self.kaslr_addr = 0x146806d0
        self.imem_offset_memdump_table = 0x10
        self.imem_file_name = 'OCIMEM.BIN'
        self.tbi_mask = 0x4000000000
        self.aff_shift = [0,0,3,0]

class BoardGlymur(Board):
    def __init__(self, socid):
        super(BoardGlymur, self).__init__()
        self.socid = socid
        self.board_num = "glymur"
        self.cpu = 'ARMV9-A'
        self.ram_start = 0x80000000
        self.smem_addr = 0x7FE00000
        self.smem_addr_buildinfo = 0x7FE09D80
        self.phys_offset = 0xA9100000
        self.imem_start = 0x14680000
        self.kaslr_addr = 0x146806d0
        self.imem_offset_memdump_table = 0x10
        self.imem_file_name = 'OCIMEM.BIN'

class BoardShikra(Board):
    def __init__(self, socid):
        super(BoardShikra, self).__init__()
        self.socid = socid
        self.board_num = "shikra"
        self.cpu = 'ARMv8.2-A'
        self.ram_start = 0x80000000
        self.smem_addr = 0x6000000
        self.smem_addr_buildinfo = 0x6007210
        self.phys_offset = 0xB5000000
        self.imem_start = 0x0C100000
        self.kaslr_addr = 0x0C11E6D0
        self.imem_offset_memdump_table = 0x10
        self.imem_file_name = 'OCIMEM.BIN'

BoardQCM6490(socid=475)
BoardQCM6490SVM(socid=475)
BoardQCM6490(socid=499)
BoardQCS9100(socid=533)
BoardQCS9100SVM(socid=533)
BoardQCS9100(socid=534)
BoardQCS9100SVM(socid=534)
BoardQCS9100(socid=667)
BoardQCS9100SVM(socid=667)
BoardQCS8300(socid=605)
BoardQCS8300(socid=606)
BoardQCS8300(socid=607)
BoardQCS8300(socid=620)
BoardQCS8300(socid=674)
BoardQCS8300(socid=675)
BoardQCS8300(socid=695)
BoardQCS8300SVM(socid=605)
BoardQCS8300SVM(socid=606)
BoardQCS8300SVM(socid=607)
BoardQCS8300SVM(socid=620)
BoardQCS8300SVM(socid=674)
BoardQCS8300SVM(socid=675)
BoardQCS8300SVM(socid=695)
BoardQCS615(socid=377)
BoardQCS615(socid=380)
BoardQCS615(socid=384)
BoardQCS615(socid=680)
BoardHamoa(socid=555)
BoardHamoa(socid=615)
BoardHamoa(socid=616)
BoardHamoa(socid=709)
BoardHamoa(socid=710)
BoardKaanapali(socid=660)
BoardKaanapali(socid=661)
BoardKaanapali(socid=730)
BoardKaanapali(socid=743)
BoardSM8750(socid=618)
BoardSM8750SVM(socid=618)
BoardSM8750(socid=639)
BoardSM8750SVM(socid=639)
BoardSM8750(socid=705)
BoardSM8750SVM(socid=705)
BoardSM8750(socid=706)
BoardSM8750SVM(socid=706)
BoardGlymur(socid=662)
BoardGlymur(socid=698)
BoardGlymur(socid=699)
BoardShikra(socid=756)
BoardShikra(socid=758)
BoardShikra(socid=759)
