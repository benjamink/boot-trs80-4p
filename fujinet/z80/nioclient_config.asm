; SPDX-License-Identifier: GPL-3.0-or-later
; Copyright (C) 2026 Benjamin Krein
; nioclient_config.asm -- the fujinet-nio client (nioclib.asm) for CONFIG/CMD, which is a C program that fills
; 3000h-CFFFh. Same entry table as nioclient.asm, relocated to D000h with its buffers at the top of user
; memory, below the resident driver at E000h:
;   D000-D8FF code (D003 = nio_request ... see nioclient.asm), D900 PB, D920 PAY, DA00 NIO_TX, DD00 NIO_RX.
          DEFINE NIO_EXTERNAL
PB        equ 0D900h
PAY       equ 0D920h
NIO_TX    equ 0DA00h
NIO_RX    equ 0DD00h
RX_MAX    equ 0300h
          org 0D000h
          jp nio_exchange
          jp nio_request
          jp disk_info
          jp disk_read
          jp disk_write
          jp disk_mount
          jp disk_unmount
          jp disk_list
          jp file_list

          include "nioclib.asm"
          ASSERT $ <= PB, "nioclient code runs into its buffers"
