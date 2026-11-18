; memtest_march.inc -- the March C- engine, included twice by memtest.asm:
; once as part of the driver (tests everything except the driver's own 4 KB) and once inside the
; relocated kernel (tests the driver's 4 KB while the driver sits in a backup copy).
;
; March C- (van de Goor) detects stuck-at, transition, address-decoder and most coupling faults:
;   1  up   w b
;   2  up   r b,  w ~b
;   3  up   r ~b, w b
;   4  down r b,  w ~b
;   5  down r ~b, w b
;   6  down r b
; in:  HL = first address, BC = length (1..FFFFh), D = background b
; out: E = bits that ever read back wrong (0 = all good), EV_ADR = address of the first wrong byte, Z set if E = 0
; uses the stack (a few words); leaves IX and IY alone.

march:      push hl
            push bc
            ld e,0
.s1:        ld (hl),d
            inc hl
            dec bc
            ld a,b
            or c
            jr nz,.s1

            pop bc                       ; step 2: up, read b, write ~b
            pop hl
            push hl
            push bc
.s2:        ld a,(hl)
            xor d
            call nz,march_mm
            ld a,d
            cpl
            ld (hl),a
            inc hl
            dec bc
            ld a,b
            or c
            jr nz,.s2

            pop bc                       ; step 3: up, read ~b, write b
            pop hl
            push hl
            push bc
.s3:        ld a,(hl)
            cpl
            xor d
            call nz,march_mm
            ld (hl),d
            inc hl
            dec bc
            ld a,b
            or c
            jr nz,.s3

            pop bc                       ; step 4: down, read b, write ~b
            pop hl
            push hl
            push bc
            add hl,bc
            dec hl
.s4:        ld a,(hl)
            xor d
            call nz,march_mm
            ld a,d
            cpl
            ld (hl),a
            dec hl
            dec bc
            ld a,b
            or c
            jr nz,.s4

            pop bc                       ; step 5: down, read ~b, write b
            pop hl
            push hl
            push bc
            add hl,bc
            dec hl
.s5:        ld a,(hl)
            cpl
            xor d
            call nz,march_mm
            ld (hl),d
            dec hl
            dec bc
            ld a,b
            or c
            jr nz,.s5

            pop bc                       ; step 6: down, read b
            pop hl
            add hl,bc
            dec hl
.s6:        ld a,(hl)
            xor d
            call nz,march_mm
            dec hl
            dec bc
            ld a,b
            or c
            jr nz,.s6

            ld a,e
            or a
            ret

; A = the bits that differ (nonzero). Adds them to E; remembers the address of the first failure.
march_mm:   push af
            ld a,e
            or a
            jr nz,.have
            ld (EV_ADR),hl
.have:      pop af
            or e
            ld e,a
            ret
