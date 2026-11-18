; memtest_k.asm -- the kernel half of memtest.asm. It runs at K_BASE (9000h) while the driver's own 4 KB
; (6000-6FFFh) is being tested: March C- over D, then D is restored from its backup at S_BASE and control
; returns to d_march's caller. Built to build/memtest_k.bin (raw) and embedded into memtest.hex by memtest.asm.

            include "memtest_defs.inc"
            org K_BASE

            module km
EV_ADR      defl K_EVADR
kmain:      ld sp,K_STACK
            xor a
            ld (K_ERR),a
            ld d,00h
            call krun
            ld d,55h
            call krun
            ld d,33h
            call krun
            ld d,0Fh
            call krun
            ld hl,S_BASE                 ; put the driver back
            ld de,D_START
            ld bc,D_LEN
            ldir
            ld sp,(V_SP)
            ld a,(K_ERR)
            ld e,a
            ld hl,(K_FIRST)
            ret                          ; to d_march's caller, from the restored stack

krun:       ld hl,D_START
            ld bc,D_LEN
            call march
            ld a,e
            or a
            ret z
            ld a,(K_ERR)
            or a
            jr nz,kr1
            ld hl,(K_EVADR)
            ld (K_FIRST),hl
kr1:        ld a,(K_ERR)
            or e
            ld (K_ERR),a
            ret

            include "memtest_march.inc"
            endmodule
