; serialcmd.asm -- LS-DOS /CMD front end for the resident monitor (mon.asm).
; Loaded at 5F00h by LS-DOS from SERIAL/CMD; the monitor itself follows at 6000h in the same file.
; Under LS-DOS the UART is not set up for us (the ROM loader did that when we booted over serial),
; so: reset it, 19200 baud, 8 data bits, odd parity, 1 stop bit, DTR+RTS (xtrs trs_uart.h bit layout:
; EAh control = 80 even-parity, 60 8 bits, 10 two stops, 08 no parity, 04 not-break, 02 DTR, 01 RTS).
; Interrupts stay off from here on: the monitor polls the UART and cannot be interrupted.
          org 5F00h
          ld hl,msg
          ld a,10                  ; @DSPLY
          rst 28h
          di
          out (0E8h),a             ; UART master reset (value ignored)
          ld a,0FFh
          out (0E9h),a             ; 19200 baud send and receive
          ld a,67h
          out (0EAh),a             ; 8 bits, odd parity, 1 stop, not-break, DTR, RTS
          jp 6000h
msg:      db "Serial link ready: 19200 baud 8O1. Run trs80put.py on the PC.",0Dh
