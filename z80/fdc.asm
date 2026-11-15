; fdc.asm -- floppy routines for the TRS-80 Model 4P. Uploaded at 8000h by trs80.fdc.Fdc and
; run through the monitor's EXEC. EXEC cannot set registers, so parameters and results live
; in a parameter block at 9F00h.
;
; Hardware (Model 4 Technical Reference Manual, FDC section; the 4P uses a WD1773):
;   F0 command (write) / status (read)   F1 track   F2 sector   F3 data
;   F4 drive-select latch (write only): D0-D3 drive 0-3 (one hot), D4 side, D5 write
;      precompensation, D6 wait-state generation (NOT used: we poll), D7 1 = MFM / 0 = FM.
;      The latch's motor one-shot lasts ~3 s, so every command rewrites the latch first.
;   E4 write: NMI mask (D7 = FDC INTRQ NMI). We write 0 so no command can raise an NMI.
;   EC write: D6 = FAST (4 MHz). Data arrives every 32 us at 250 kbps, so the byte loops
;      below (~21 us worst case at 4 MHz) need 4 MHz. init sets it.
; Status bits: 0 BUSY, 1 DRQ, 2 TR00 (type I) / LOST DATA, 3 CRC error, 4 RNF (seek error),
;      5 write fault, 6 write protect, 7 not ready.
; Commands used: 03 restore (6..30 ms steps, no verify), 13 seek (no verify), C4 read address,
;      84 read sector, F4 write track, D0 force interrupt.
;
; Entry points (jump table): 8000 init, 8003 restore, 8006 seek, 8009 read_addr,
;      800C read_sector, 800F arm_write, 8012 write_track.

PB        equ 9F00h
PB_LATCH  equ PB+0     ; value for F4 before each command
PB_TRACK  equ PB+1     ; seek destination
PB_SECTOR equ PB+2
PB_BUF    equ PB+3     ; word: buffer address
PB_STATUS equ PB+5     ; FDC status read after the command finished
PB_ERR    equ PB+6     ; 0 ok, 1 write not armed (nothing touched), 2 timeout (aborted with D0)
PB_ARMED  equ PB+7     ; A5h = next write_track is allowed; cleared by write_track
PB_SPIN   equ PB+8     ; nonzero: wait ~0.4 s for the motor first

F_CMD     equ 0F0h
F_TRK     equ 0F1h
F_SEC     equ 0F2h
F_DAT     equ 0F3h
F_SEL     equ 0F4h

          org 8000h
          jp init
          jp restore
          jp seek
          jp read_addr
          jp read_sector
          jp arm_write
          jp write_track

init:     xor a
          out (0E4h),a             ; no NMI sources
          ld (PB_ARMED),a
          ld a,40h
          out (0ECh),a             ; FAST, everything else off
          ret

arm_write: ld a,0A5h
          ld (PB_ARMED),a
          ret

; select drive/side/density, clear the error code, optionally wait for the motor
select:   ld a,(PB_LATCH)
          out (F_SEL),a
          xor a
          ld (PB_ERR),a
          ld a,(PB_SPIN)
          or a
          ret z
          ld bc,0                  ; 65536 x 26 T-states ~ 0.43 s at 4 MHz
sp1:      dec bc
          ld a,b
          or c
          jr nz,sp1
          ret

; the controller needs ~28 us before its BUSY bit is valid after a command write
delay50:  ld b,16
d50:      djnz d50
          ret

; wait until not busy (type I commands). Carry set = timed out (~6 s).
wait_idle: call delay50
          ld d,8
wi1:      ld bc,0
wi2:      in a,(F_CMD)
          rra
          ret nc
          dec bc
          ld a,b
          or c
          jr nz,wi2
          dec d
          jr nz,wi1
          scf
          ret

; finish a type I command: wait, then store the final status
finish:   call wait_idle
          jp nc,done_status
aborted:  ld a,0D0h                ; force interrupt
          out (F_CMD),a
          ld a,2
          ld (PB_ERR),a
done_status: in a,(F_CMD)
          ld (PB_STATUS),a
          ret

restore:  call select
          ld a,03h
          out (F_CMD),a
          jp finish

seek:     call select
          ld a,(PB_TRACK)
          out (F_DAT),a
          ld a,13h
          out (F_CMD),a
          jp finish

read_addr: call select
          ld hl,(PB_BUF)
          ld a,0C4h
          out (F_CMD),a
          jp xfer_in

read_sector: call select
          ld a,(PB_SECTOR)
          out (F_SEC),a
          ld hl,(PB_BUF)
          ld a,84h
          out (F_CMD),a
          jp xfer_in

write_track: ld a,(PB_ARMED)
          cp 0A5h
          jr z,wt_go
          ld a,1                   ; refuse: no port is touched
          ld (PB_ERR),a
          ret
wt_go:    xor a
          ld (PB_ARMED),a
          call select
          ld hl,(PB_BUF)
          ld a,0F4h
          out (F_CMD),a
          jp xfer_out

; ---- data transfer: first wait (with timeout) for DRQ or completion, then a tight loop ----
xfer_in:  call delay50
          ld de,0                  ; ~1 s at 4 MHz
xia:      in a,(F_CMD)
          rra
          jp nc,done_status        ; not busy: finished (e.g. RNF)
          rra
          jr c,xi_fast             ; DRQ up
          dec de
          ld a,d
          or e
          jr nz,xia
          jp aborted
xi_fast:  in a,(F_CMD)             ; ---- 62 T per byte, 47 T idle ----
          bit 1,a
          jr z,xi_chk
          in a,(F_DAT)
          ld (hl),a
          inc hl
          jr xi_fast
xi_chk:   rra
          jr c,xi_fast
          jp done_status

xfer_out: call delay50
          ld de,0
xoa:      in a,(F_CMD)
          rra
          jp nc,done_status
          rra
          jr c,xo_fast
          dec de
          ld a,d
          or e
          jr nz,xoa
          jp aborted
xo_fast:  in a,(F_CMD)
          bit 1,a
          jr z,xo_chk
          ld a,(hl)
          out (F_DAT),a
          inc hl
          jr xo_fast
xo_chk:   rra
          jr c,xo_fast
          jp done_status
