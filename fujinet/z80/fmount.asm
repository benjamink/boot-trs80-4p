; FMOUNT -- mount a disk image from the FujiNet on a drive.   FMOUNT :d uri [RO|RW] [SS=bytes]
; :d is the LS-DOS drive (0-7), which is FujiNet slot d+1. The URI is whatever fujinet-nio takes:
; host:/path, sd0:/path, tnfs://host/path. Mirrors FMOUNT of nio-core-apps (see docs/superpowers/plans).
          include "fcli.asm"

main:     ld hl,(CMDP)
          call parse_drive
          jp c,usage
          ld (drive),a
          inc a
          ld (PB),a                ; slot
          call skip_sp
          ld a,(hl)
          call at_end
          jp z,usage
          call word_len
          ld a,b
          or a
          jp nz,usage              ; longer than 255
          ld (PB+20),hl
          ld (PB+22),bc
          add hl,bc
          xor a
          ld (PB+19),a
          ld (PB+24),a
          ld (PB+25),a
opt_loop: call skip_sp
          ld a,(hl)
          call at_end
          jr z,do_mount
          ld de,w_ro
          call word_is
          jr nz,o2
          ld a,1
          ld (PB+19),a
          jr opt_loop
o2:       ld de,w_rw
          call word_is
          jr nz,o3
          xor a
          ld (PB+19),a
          jr opt_loop
o3:       ld de,w_ss
          call prefix_is
          jp nz,usage
          call parse_num
          jp c,usage
          ld a,d                   ; 128, 256 ... 4096: a power of two in range
          or a
          jr nz,ss_hi
          ld a,e
          cp 128
          jp c,usage
          jr ss_pow
ss_hi:    ld a,d
          cp 17
          jp nc,usage
ss_pow:   push hl
          ld h,d
          ld l,e
          dec hl
          ld a,h
          and d
          ld b,a
          ld a,l
          and e
          or b
          pop hl
          jp nz,usage              ; not a power of two
          ld (PB+24),de
          jr opt_loop

do_mount: call disk_mount
          jr z,mounted
          call report
          ld a,2
          ret
mounted:  call line_start
          ld hl,m_mounted
          call line_add
          ld a,(drive)
          add a,'0'
          ld (digit),a
          ld hl,digit
          call line_add
          ld hl,m_paren
          call line_add
          ld hl,(PB+17)            ; sector count, high word
          ld a,h
          or l
          ld hl,(PB+15)
          jr z,count_ok
          ld hl,65535              ; saturate: LS-DOS never sees more than this on a floppy-sized image
count_ok: call line_dec
          ld hl,m_sectors
          call line_add
          call line_show
          ld hl,(PB+13)
          ld de,256
          or a
          sbc hl,de
          jr z,narrow_ok
          ld hl,m_wide
          call print
narrow_ok: xor a
          ret

usage:    ld hl,m_usage
          call print
          ld a,1
          ret

; does the word at HL start with the (upper-case) text at DE? Z yes, HL moves past it
prefix_is:
          push hl
pf_l:     ld a,(de)
          or a
          jr z,pf_yes
          ld c,a
          ld a,(hl)
          call upper
          cp c
          jr nz,pf_no
          inc hl
          inc de
          jr pf_l
pf_yes:   pop af
          xor a
          ret
pf_no:    pop hl
          or 1
          ret

drive:    db 0
digit:    db 0,0
w_ro:     db "RO",0
w_rw:     db "RW",0
w_ss:     db "SS=",0
m_mounted: db "Mounted :",0
m_paren:  db " (",0
m_sectors: db " sectors)",0
m_wide:   db "Warning: the sector size is not 256, so LS-DOS cannot use this image",0Dh
m_usage:  db "Usage: FMOUNT :d uri [RO|RW] [SS=bytes]   (d = drive 0-7)",0Dh

          include "nioclib.asm"
