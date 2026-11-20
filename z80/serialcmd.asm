; SPDX-License-Identifier: GPL-3.0-or-later
; Copyright (C) 2026 Benjamin Krein
; serialcmd.asm -- LS-DOS /CMD front end for the resident monitor (mon.asm).
; Loaded at 5F00h by LS-DOS from SERIAL/CMD; the monitor itself follows at 6000h in the same file.
; Under LS-DOS the UART is not set up for us (the ROM loader did that when we booted over serial), so it is
; programmed here exactly as the 4P ROM does it: EAh = 64h (8 data bits, odd parity, 1 stop, not-break), E9h = FFh
; (19200 baud both ways), then E8h = FFh. Writing 0 to E8h leaves MAME's UART at 5 data bits, so use the ROM's value.
; Interrupts stay off from here on: the monitor polls the UART and cannot be interrupted.
          org 5F00h
          ld hl,msg
          ld a,10                  ; @DSPLY
          rst 28h
          di
          ld a,64h
          out (0EAh),a             ; control: 8 bits, odd parity, 1 stop, not-break (as the 4P ROM sets it)
          ld a,0FFh
          out (0E9h),a             ; 19200 baud send and receive
          out (0E8h),a             ; master reset / enable the control register load: the VALUE MATTERS in MAME (0 breaks it)
          jp 6000h
msg:      db "Serial link ready: 19200 baud 8O1. Run trs80put.py on the PC.",0Dh
