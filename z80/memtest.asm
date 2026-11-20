; SPDX-License-Identifier: GPL-3.0-or-later
; Copyright (C) 2026 Benjamin Krein
; memtest.asm -- comprehensive RAM test for the TRS-80 Model 4P (64 KB or 128 KB), loaded by the ROM serial
; loader at 6000h (trs80boot.py build/memtest.hex --terminal). Reports over the RS-232 port (UART already set to
; 19200 baud 8O1 by the ROM loader) and keeps repeating until reset.
;
; Memory model (port 84h, as used by the diagnostic ROM and by MAME's trs80m3.cpp):
;   bits 1-0 = 3  "map IV": all of 0000-FFFF is RAM (no ROM, keyboard or video)
;   bit 5 = 1 (enable), bit 6 = 0 (despage = upper half), bit 4 = srcpage: a 32 KB half of the second 64 KB bank
;   replaces CPU 8000-FFFF. So CPU 8000-FFFF shows physical 08000 (view 03h), 10000 (view 23h) or 18000 (view 33h);
;   CPU 0000-7FFF is physical 00000-07FFF in all three views.
;
; What is run, per pass:
;   1. random fill of every window, a few seconds of waiting (DRAM refresh / retention), then verify
;      (also catches address-line faults and a second 64 KB bank that aliases the first)
;   2. March C- (see memtest_march.inc) over every window with backgrounds 00/FF, 55/AA, 33/CC, 0F/F0
;   3. the driver's own 4 KB (6000-6FFF): its contents are copied to 8000h, a copy of the March engine is run from
;      9000h, tests 6000-6FFF with the same four backgrounds, and puts the contents back.
;
; The two 1 KB pages of video RAM are tested like the rest (their contents show on the screen as the test runs).
;
; Output is one line per window and test, e.g.   10000-17FFF  march 55/AA: FAIL bits ....3... first @ 8123
; "bits" are D7..D0 (one DRAM chip per bit and bank). Lines end with CR only (trs80boot.py --terminal adds the LF).

            include "memtest_defs.inc"

            org D_START

start:      di
            ld sp,STACK_TOP
            xor a
            out (0E4h),a                 ; no NMIs
            ld a,VIEW0
            call set_view
            ld hl,m_banner
            call puts
            call detect_bank2
            ld hl,0
            ld (V_PASS),hl

pass:       ld hl,(V_PASS)
            inc hl
            ld (V_PASS),hl
            ld hl,0
            ld (V_FAILS),hl
            ld hl,m_pass
            call puts
            ld hl,(V_PASS)
            call put_dec16
            call crlf

; ---- 1. random fill, wait, verify
            ld hl,m_fill
            call puts
            call crlf
            call rnd_all_start
fill_loop:  call next_window
            jr z,fill_done
            ld a,(V_SEED)
            call rfill
            call seed_next
            jr fill_loop
fill_done:  ld hl,m_wait
            call puts
            call crlf
            call delay
            call rnd_all_start
ver_loop:   call next_window
            jr z,ver_done
            push hl
            call rep_head
            ld hl,t_random
            call puts
            pop hl
            ld a,(V_SEED)
            ld d,a
            call rverify
            call rep_tail
            call seed_next
            jr ver_loop
ver_done:

; ---- 2. March C- on every window, four backgrounds
            ld hl,bg_table
            ld (V_BGP),hl
bg_loop:    ld hl,(V_BGP)
            ld a,(hl)
            ld (V_BG),a
            ld hl,windows
            ld (V_WPTR),hl
win_loop:   call next_window
            jr z,win_done
            push hl
            call rep_head
            call put_march_name
            pop hl
            ld a,(V_BG)
            ld d,a
            call dm.march
            call rep_tail
            jr win_loop
win_done:   ld hl,(V_BGP)
            inc hl
            ld (V_BGP),hl
            ld de,bg_end
            or a
            sbc hl,de
            jr nz,bg_loop

; ---- 3. the driver's own 4 KB through the relocated kernel
            ld a,VIEW0
            call set_view
            ld hl,m_dlabel
            ld (V_LABEL),hl
            call rep_head
            ld hl,t_dmarch
            call puts
            call d_march                 ; E = failing bits, HL = first failing address
            ld (V_ERRADR),hl
            call rep_tail

            ld hl,m_done1
            call puts
            ld hl,(V_PASS)
            call put_dec16
            ld hl,(V_FAILS)
            ld a,h
            or l
            jr nz,failed
            ld hl,m_ok2
            call puts
            call crlf
            jp pass
failed:     ld hl,m_bad2
            call puts
            ld hl,(V_FAILS)
            call put_dec16
            ld hl,m_bad3
            call puts
            call crlf
            jp pass

; ---- windows: view, base, length, label.  CPU addresses; the label names the physical range.
windows:    db VIEW0
            dw 0000h, 6000h, w_lab1
            db VIEW0
            dw 7000h, 1000h, w_lab2
            db VIEW0
            dw 8000h, 8000h, w_lab3
            db VIEW_V0                   ; video RAM, two 1 KB pages (map I: no ROM needed above 3C00)
            dw 3C00h, 0400h, w_labv0
            db VIEW_V1
            dw 3C00h, 0400h, w_labv1
win4:       db VIEW2
            dw 8000h, 8000h, w_lab4
win5:       db VIEW3
            dw 8000h, 8000h, w_lab5
            db 0FFh
bg_table:   db 00h, 55h, 33h, 0Fh
bg_end:

; Take the next window: sets its view, returns HL = base, BC = length, V_LABEL = label. Z if there is none.
next_window:ld hl,(V_WPTR)
            ld a,(hl)
            cp 0FFh
            ret z
            inc hl
            call set_view
            ld e,(hl)
            inc hl
            ld d,(hl)
            inc hl
            ld c,(hl)
            inc hl
            ld b,(hl)
            inc hl
            push de
            ld e,(hl)
            inc hl
            ld d,(hl)
            inc hl
            ld (V_LABEL),de
            ld (V_WPTR),hl
            pop hl
            or 1                         ; NZ
            ret

; Rewind to the first window and pick this pass's first seed (never 0).
rnd_all_start:
            ld hl,windows
            ld (V_WPTR),hl
            ld a,(V_PASS)
            add a,a
            add a,a
            add a,a
            and 7Fh
            or 1
            ld (V_SEED),a
            ret

seed_next:  ld a,(V_SEED)
            add a,29
            jr nz,sn1
            inc a
sn1:        ld (V_SEED),a
            ret

; Is there a second 64 KB bank? Writes different bytes through views 03h, 23h and 33h and checks that they
; stay apart. A view that aliases an earlier one is dropped from the window list (a 64 KB machine has none).
detect_bank2:
            ld a,VIEW0
            call set_view
            ld a,0A5h
            ld (8000h),a
            ld a,VIEW2
            call set_view
            ld a,5Ah
            ld (8000h),a
            ld a,VIEW3
            call set_view
            ld a,0C3h
            ld (8000h),a
            ld a,VIEW0                   ; view 03h must still hold A5
            call set_view
            ld a,(8000h)
            cp 0A5h
            jr nz,db_none
            ld a,VIEW2                   ; view 23h must still hold 5A
            call set_view
            ld a,(8000h)
            cp 5Ah
            jr nz,db_none
            ld a,VIEW3                   ; view 33h must hold C3
            call set_view
            ld a,(8000h)
            cp 0C3h
            jr nz,db_none
            ld a,VIEW0
            call set_view
            ld hl,m_two_banks
            jp puts
db_none:    xor a
            ld (win4),a                  ; end the window list before the second bank
            ld a,VIEW0
            call set_view
            ld hl,m_one_bank
            jp puts

set_view:   ld (V_VIEW),a
            out (OPREG),a
            ret

; HL = first address, BC = length, A = seed. 8-bit maximal LFSR stream (x^8+x^6+x^5+x^4+1, period 255).
rfill:      ld (hl),a
            inc hl
            srl a
            jr nc,rf1
            xor 0B8h
rf1:        dec bc
            ld d,a
            ld a,b
            or c
            ld a,d
            jr nz,rfill
            ret

; HL = first address, BC = length, D = seed. Returns E = wrong bits, V_ERRADR = first wrong address.
rverify:    ld e,0
rv1:        ld a,(hl)
            xor d
            call nz,dm.march_mm
            ld a,d
            srl a
            jr nc,rv2
            xor 0B8h
rv2:        ld d,a
            inc hl
            dec bc
            ld a,b
            or c
            jr nz,rv1
            ld a,e
            or a
            ret

; A few seconds, to let DRAM cells that cannot hold their charge show up.
delay:      ld b,8
dl1:        ld hl,0
dl2:        dec hl
            ld a,h
            or l
            jr nz,dl2
            djnz dl1
            ret

; ---- the driver's own memory
; Saves D at 8000h, copies the kernel to 9000h and jumps there; the kernel tests 6000-6FFF, restores it and returns here.
d_march:    ld a,VIEW0
            call set_view
            ld (V_SP),sp
            ld hl,D_START
            ld de,S_BASE
            ld bc,D_LEN
            ldir
            ld hl,k_image
            ld de,K_BASE
            ld bc,K_LEN
            ldir
            jp K_BASE

; ---- reporting
rep_head:   ld hl,m_two
            call puts
            ld hl,(V_LABEL)
            call puts
            ld hl,m_two
            jp puts

put_march_name:
            ld hl,t_march
            call puts
            ld a,(V_BG)
            call put_hex8
            ld a,'/'
            call tx_byte
            ld a,(V_BG)
            cpl
            call put_hex8
            ret

; E = wrong bits (0 = good), V_ERRADR = first wrong address. Ends the line.
rep_tail:   ld a,e
            or a
            jr nz,rt_bad
            ld hl,m_okline
            call puts
            jp crlf
rt_bad:     ld hl,m_fail
            call puts
            ld b,8
            ld d,'7'
rt1:        rlc e
            ld a,'.'
            jr nc,rt2
            ld a,d
rt2:        call tx_byte
            dec d
            djnz rt1
            ld hl,m_first
            call puts
            ld hl,(V_ERRADR)
            call put_hex16
            ld hl,(V_FAILS)
            inc hl
            ld (V_FAILS),hl
            jp crlf

; ---- UART
tx_byte:    out (UART_DATA),a
            push bc
            ld bc,120                    ; about 3100 T-states: longer than one character at 19200 baud
tx1:        dec bc
            ld a,b
            or c
            jr nz,tx1
            pop bc
            ret

puts:       ld a,(hl)
            or a
            ret z
            call tx_byte
            inc hl
            jr puts

crlf:       ld a,0Dh
            jp tx_byte

put_hex16:  ld a,h
            call put_hex8
            ld a,l
put_hex8:   push af
            rrca
            rrca
            rrca
            rrca
            call put_nib
            pop af
put_nib:    and 0Fh
            add a,'0'
            cp '9'+1
            jr c,pn1
            add a,7
pn1:        jp tx_byte

; HL as decimal without leading zeros
put_dec16:  xor a
            ld (V_LZ),a
            ld bc,-10000
            call pd_digit
            ld bc,-1000
            call pd_digit
            ld bc,-100
            call pd_digit
            ld bc,-10
            call pd_digit
            ld a,1
            ld (V_LZ),a
            ld bc,-1
pd_digit:   ld a,'0'-1
pd1:        inc a
            add hl,bc
            jr c,pd1
            sbc hl,bc
            cp '0'
            jr nz,pd2
            ld d,a
            ld a,(V_LZ)
            or a
            ld a,d
            ret z
pd2:        ld d,a
            ld a,1
            ld (V_LZ),a
            ld a,d
            jp tx_byte

; ---- the March C- engine, driver copy
            module dm
EV_ADR      defl V_ERRADR
            include "memtest_march.inc"
            endmodule

; ---- text
m_banner:   db 0Dh,"TRS-80 4P RAM TEST  (reset to stop)",0Dh
            db "windows are physical RAM: 00000-0FFFF = first 64K, 10000-1FFFF = second 64K bank (port 84h)",0Dh
            db "bits D7..D0 are one DRAM chip each per bank",0Dh,0
m_two_banks:db "second 64K bank found: testing 128K",0Dh,0
m_one_bank: db "no second 64K bank (port 84h does not change what CPU 8000-FFFF shows): testing 64K",0Dh,0
m_pass:     db 0Dh,"Pass ",0
m_fill:     db "random fill of every window",0
m_wait:     db "waiting a few seconds for the DRAM to forget, then verifying",0
m_two:      db "  ",0
m_okline:   db ": OK",0
m_fail:     db ": FAIL bits ",0
m_first:    db " first @",0
m_dlabel:   db "06000-06FFF",0
w_lab1:     db "00000-05FFF",0
w_lab2:     db "07000-07FFF",0
w_lab3:     db "08000-0FFFF",0
w_lab4:     db "10000-17FFF",0
w_lab5:     db "18000-1FFFF",0
w_labv0:    db "VRAM page 0 (3C00-3FFF)",0
w_labv1:    db "VRAM page 1 (3C00-3FFF)",0
t_random:   db "random",0
t_march:    db "march ",0
t_dmarch:   db "march 00/FF 55/AA 33/CC 0F/F0 (via relocated kernel)",0
m_done1:    db "Pass ",0
m_ok2:      db " complete: no errors",0
m_bad2:     db " complete: ",0
m_bad3:     db " failing tests",0

; ---- the kernel: runs at 9000h while 6000-6FFFh is under test. Assembled separately (memtest_k.asm, origin 9000h)
; because the Intel HEX writer puts displaced code at its run address; here it travels inside the driver and is copied.
k_image:    incbin "build/memtest_k.bin"
K_LEN       equ $ - k_image
