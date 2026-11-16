; fcli.asm -- shared start-up and helpers for the LS-DOS command programs that talk to a FujiNet
; (FMOUNT, FUMOUNT, FDRIVE, ...). Include first, then define `main`, then include "nioclib.asm".
;
; LS-DOS runs a /CMD program with HL = its command line (text after the program name, ended by 0Dh).
; The UART is set up here (19200 baud 8O1, as serialcmd.asm does) and interrupts stay off while the
; program runs, because the UART has no FIFO; they are switched on around every @DSPLY and at exit.
; main returns A = return code (0 ok, 1 usage, 2 failed).
          org 3000h
cli_start:
          ld (CMDP),hl
          di
          ld a,64h
          out (0EAh),a             ; control: 8 bits, odd parity, 1 stop, not-break (as the 4P ROM sets it)
          ld a,0FFh
          out (0E9h),a             ; 19200 baud send and receive
          out (0E8h),a             ; master reset / enable the control register load: the VALUE MATTERS in MAME (0 breaks it)
          call main
          ld l,a
          ld h,0
          ei
          ld a,22                  ; @EXIT, HL = return code
          rst 28h
cli_hang: jr cli_hang

CMDP:     dw 0
numbuf:   ds 7

; print the 0Dh-terminated text at HL (and a new line)
print:    ei
          ld a,10                  ; @DSPLY
          rst 28h
          di
          ret

; print HL as an unsigned decimal number (no new line is added by us: the text ends with 0Dh)
; used as a prefix, so see print_dec_nl for the CR-less variant
; HL = number -> HL = start of digits in numbuf, 0Dh-terminated
dec_str:  ld de,numbuf+6
          ld a,0Dh
          ld (de),a
ds_loop:  xor a
          ld b,16
ds_div:   add hl,hl
          rla
          cp 10
          jr c,ds_nc
          sub 10
          inc l
ds_nc:    djnz ds_div
          add a,'0'
          dec de
          ld (de),a
          ld a,h
          or l
          jr nz,ds_loop
          ex de,hl
          ret

; CR-less text output helpers: @DSPLY always ends a line, so messages with numbers are put together in
; `line` first and shown with print.
line:     ds 80
lp:       dw 0
line_start:
          ld hl,line
          ld (lp),hl
          ret
; append the 0Dh/00h-terminated string at HL (terminator not copied)
line_add: ld de,(lp)
la_l:     ld a,(hl)
          cp 0Dh
          jr z,la_x
          or a
          jr z,la_x
          ld (de),a
          inc de
          inc hl
          jr la_l
la_x:     ld (lp),de
          ret
; append the decimal digits of HL
line_dec: call dec_str
          jr line_add
line_show:
          ld hl,(lp)
          ld (hl),0Dh
          ld hl,line
          jp print

; ---- command line scanning ----
skip_sp:  ld a,(hl)
          cp ' '
          ret nz
          inc hl
          jr skip_sp

; Z if A ends a word (space, CR or 0)
at_end:   cp ' '
          ret z
          cp 0Dh
          ret z
          or a
          ret

upper:    cp 'a'
          ret c
          cp 'z'+1
          ret nc
          and 5Fh
          ret

; HL -> a drive such as ":2" or "2" (0-7) -> A = drive, HL past it; CF=1 if not a drive
parse_drive:
          call skip_sp
          ld a,(hl)
          cp ':'
          jr nz,pd_digit
          inc hl
          ld a,(hl)
pd_digit: sub '0'
          cp 8
          jr nc,pd_bad
          ld c,a
          inc hl
          ld a,(hl)
          call at_end
          jr nz,pd_bad
          ld a,c
          or a                     ; CF=0
          ret
pd_bad:   scf
          ret

; HL -> start of a word; BC = its length, HL unchanged
word_len: push hl
          ld bc,0
wl_l:     ld a,(hl)
          call at_end
          jr z,wl_x
          inc hl
          inc bc
          jr wl_l
wl_x:     pop hl
          ret

; Does the word at HL equal the (upper-case, 0-terminated) text at DE, ignoring case? Z if so; HL moves past
; the match when it does.
word_is:  push hl
wi_l:     ld a,(de)
          or a
          jr z,wi_end
          ld c,a
          ld a,(hl)
          call upper
          cp c
          jr nz,wi_no
          inc hl
          inc de
          jr wi_l
wi_end:   ld a,(hl)
          call at_end
          jr nz,wi_no
          pop af                   ; keep the advanced HL
          xor a
          ret
wi_no:    pop hl
          or 1
          ret

; HL -> digits (1-4 of them, then a word end) -> DE = value, CF=1 if not a number
parse_num:
          ld de,0
          ld b,0
pn_l:     ld a,(hl)
          sub '0'
          cp 10
          jr nc,pn_x
          inc b
          push hl
          ld h,d
          ld l,e
          add hl,hl
          add hl,hl
          add hl,de
          add hl,hl                ; *10
          ld e,a
          ld d,0
          add hl,de
          ex de,hl
          pop hl
          inc hl
          jr pn_l
pn_x:     ld a,b
          or a
          jr z,pn_bad
          cp 5
          jr nc,pn_bad
          ld a,(hl)
          call at_end
          jr nz,pn_bad
          or a
          ret
pn_bad:   scf
          ret

; ---- error reporting for the DiskDevice calls (parameter block PB) ----
; Prints why the last disk_* call failed.
report:   ld a,(PB+8)
          cp 6
          jr z,rp_nio
          ld hl,m_noanswer
          jp print
rp_nio:   ld a,(PB+11)
          ld hl,errtab
rp_find:  ld b,(hl)
          inc hl
          inc b
          dec b
          jr z,rp_other            ; table end
          ld e,(hl)
          inc hl
          ld d,(hl)
          inc hl
          cp b
          jr nz,rp_find
          ex de,hl
          jp print
rp_other: call line_start
          ld hl,m_refused
          call line_add
          ld a,(PB+11)
          ld l,a
          ld h,0
          call line_dec
          ld hl,m_close
          call line_add
          jp line_show

m_close:  db ")",0
m_noanswer: db "No valid answer from the FujiNet - check the cable, and that NIO is running",0Dh
m_refused:  db "The FujiNet refused the request (disk error ",0

; DiskError codes (fujinet-nio disk_types.h) with something a person can act on
errtab:   db 1
          dw e_slot
          db 3
          dw e_nofs
          db 4
          dw e_nofile
          db 6
          dw e_open
          db 7
          dw e_type
          db 8
          dw e_bad
          db 9
          dw e_geom
          db 10
          dw e_nomount
          db 11
          dw e_ro
          db 12
          dw e_range
          db 13
          dw e_io
          db 15
          dw e_needss
          db 0
e_slot:   db "That drive number is not available on the FujiNet",0Dh
e_nofs:   db "The FujiNet does not know that kind of location (host:, sd0:, tnfs://...)",0Dh
e_nofile: db "Image not found",0Dh
e_open:   db "The image could not be opened",0Dh
e_type:   db "Unsupported image type",0Dh
e_bad:    db "The image is damaged or not what its name says",0Dh
e_geom:   db "The sector size does not fit the image",0Dh
e_nomount: db "Nothing mounted there",0Dh
e_ro:     db "That image is read-only",0Dh
e_range:  db "Past the end of the image",0Dh
e_io:     db "Disk I/O error on the FujiNet side",0Dh
e_needss: db "The FujiNet cannot tell the sector size of this image: add SS=256",0Dh

; ---- paged text listings (FDRIVE, FLS) ----
; list_all: DE = a fetch routine (disk_list or file_list: Z = ok), whose request the caller has already put in PB.
; Prints every line the FujiNet returns, following the "more" flag. Returns CF=1 on failure (reason in PB, see
; `report`), otherwise CF=0 and HL = the number of lines shown.
list_all: ld (fetcher),de
          ld hl,0
          ld (lstart),hl
          ld (shown),hl
la_page:  ld hl,listbuf
          ld (PB+5),hl
          ld hl,(lstart)
          ld (PB+26),hl
          ld hl,la_ret
          push hl
          ld hl,(fetcher)
          jp (hl)
la_ret:   jr z,la_got
          scf
          ret
la_got:   ld hl,(PB+9)             ; text length
          ld a,h
          or l
          jr z,la_next
          ld bc,(PB+9)
          ld hl,listbuf
la_line:  ld a,b
          or c
          jr z,la_next
          push hl                  ; start of this line
la_find:  ld a,(hl)
          cp 0Ah
          jr z,la_eol
          inc hl
          dec bc
          ld a,b
          or c
          jr nz,la_find
          ld (hl),0Dh              ; no final newline: end the line here (the buffer has a spare byte)
          jr la_show
la_eol:   ld (hl),0Dh
          inc hl
          dec bc
la_show:  ex (sp),hl               ; HL = line start, stack = next line
          push bc
          call print
          pop bc
          pop hl
          jr la_line
la_next:  ld hl,(PB+29)            ; entries in this page
          ld de,(shown)
          add hl,de
          ld (shown),hl
          ld hl,(PB+29)
          ld a,h
          or l
          jr z,la_end              ; "more" with nothing delivered: stop rather than loop forever
          ld de,(lstart)
          add hl,de
          ld (lstart),hl
          ld a,(PB+28)
          or a
          jr nz,la_page
la_end:   ld hl,(shown)
          or a
          ret

fetcher:  dw 0
lstart:   dw 0
shown:    dw 0
listbuf:  ds 250
