; memtest_defs.inc -- addresses and port numbers shared by memtest.asm and memtest_k.asm

UART_ST     equ 0EAh
UART_DATA   equ 0EBh
OPREG       equ 84h

VIEW0       equ 03h                      ; map IV, CPU 8000-FFFF = physical 08000
VIEW_V0     equ 00h                      ; map I (ROM at 0, video RAM at 3C00), video page 0
VIEW_V1     equ 80h                      ;                                      video page 1
VIEW2       equ 23h                      ;                          physical 10000
VIEW3       equ 33h                      ;                          physical 18000

D_START     equ 6000h                    ; the driver: code, variables, stack
D_LEN       equ 1000h
STACK_TOP   equ 7000h
S_BASE      equ 8000h                    ; where D is saved while it is being tested
K_BASE      equ 9000h                    ; the relocated kernel
K_EVADR     equ 9F00h                    ; kernel variables, and its stack below them
K_ERR       equ 9F02h
K_FIRST     equ 9F03h
K_STACK     equ 9F00h

V_SP        equ 6E00h
V_VIEW      equ 6E02h
V_PASS      equ 6E03h
V_FAILS     equ 6E05h
V_ERRADR    equ 6E07h
V_WPTR      equ 6E09h
V_LABEL     equ 6E0Bh
V_BG        equ 6E0Dh
V_SEED      equ 6E0Eh
V_LZ        equ 6E0Fh
V_BGP       equ 6E10h
