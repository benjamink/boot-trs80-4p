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
; Write Track cannot carry data bytes F5/F6/F7 (they are controller commands), so tracks are
; formatted with filler and every sector is then written with Write Sector (A4, normal data mark).
; Commands used: 03 restore (6..30 ms steps, no verify), 17 seek (with verify, 15 ms head settle), C4 read address,
;      84 read sector, F4 write track, D0 force interrupt.
;
; Entry points (jump table): 8000 init, 8003 restore, 8006 seek, 8009 read_addr,
;      800C read_sector, 800F arm_write, 8012 write_track, 8015 write_sector, 8018 disarm.

PB        equ 9F00h
PB_LATCH  equ PB+0     ; value for F4 before each command
PB_TRACK  equ PB+1     ; seek destination
PB_SECTOR equ PB+2
PB_BUF    equ PB+3     ; word: buffer address
PB_STATUS equ PB+5     ; FDC status read after the command finished
PB_ERR    equ PB+6     ; 0 ok, 1 write not armed (nothing touched), 2 timeout (aborted with D0)
PB_ARMED  equ PB+7     ; A5h = next write_track is allowed; cleared by write_track
PB_SPIN   equ PB+8     ; nonzero: wait ~0.4 s for the motor first
PB_DEL    equ PB+10    ; bit 0 = write the DELETED data mark F8 (LS-DOS directory sectors); other bits ignored
PB_NOVERIFY equ PB+11 ; nonzero: seek without verify (13h) -- probing past the last track must not search for an ID
PB_ARMED_S equ PB+9    ; A5h = write_sector is allowed; cleared only by disarm/init

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
          jp write_sector
          jp disarm

init:     di
          xor a
          out (0E4h),a             ; no NMI sources
          ld (PB_ARMED),a
          ld (PB_ARMED_S),a
          ld a,40h
          out (0ECh),a             ; FAST, everything else off
          ret

arm_write: ld a,0A5h
          ld (PB_ARMED),a
          ld (PB_ARMED_S),a
          ret

disarm:   xor a
          ld (PB_ARMED),a
          ld (PB_ARMED_S),a
          ret

write_sector: ld a,(PB_ARMED_S)
          cp 0A5h
          jr z,ws_go
          ld a,1                   ; refuse: no port is touched
          ld (PB_ERR),a
          ret
ws_go:    call select
          ld a,(PB_SECTOR)
          out (F_SEC),a
          ld hl,(PB_BUF)
          ld a,(PB_DEL)
          and 1
          or 0A4h                  ; A4 = data mark FB, A5 = deleted mark F8
          out (F_CMD),a
          jp xfer_out

; select drive/side/density, clear the error code, optionally wait for the motor
select:   di                       ; the 60 Hz clock interrupt would steal ~100 us mid-transfer (32 us/byte)
          ld a,(PB_LATCH)
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
          ld a,17h                 ; seek + verify: 15 ms head settle
          ld hl,PB_NOVERIFY
          bit 0,(hl)
          jr z,sk_go
          ld a,13h
sk_go:    out (F_CMD),a
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

; ---- data transfer ----
; Every byte: OUT to the drive-select latch with WSGEN (D6) set holds the CPU in WAIT until the
; controller raises DRQ or INTRQ (hardware watchdog 1024 us), then IN status / IN or OUT data. That keeps
; the gap between DRQ and our data access to ~37 T-states (a byte lasts 32 us). Polling first and
; then branching into a loop was ~110 T and lost byte 0 on real hardware (measured on the 4P).
; BC counts empty waits (<= ~1 ms each): about 3 s before giving up and sending Force Interrupt.
xfer_in:  call delay50
          ld bc,3000
          ld a,(PB_LATCH)
          or 40h
          ld d,a
xi_l:     ld a,d
          out (F_SEL),a
          in a,(F_CMD)
          bit 1,a
          jr z,xi_none
          in a,(F_DAT)
          ld (hl),a
          inc hl
          ld bc,3000               ; timeout counts empty waits since the LAST byte
          jr xi_l
xi_none:  rra
          jp nc,done_status        ; not busy: the command has finished
          dec bc
          ld a,b
          or c
          jr nz,xi_l
          jp aborted

xfer_out: call delay50
          ld bc,3000
          ld a,(PB_LATCH)
          or 40h
          ld d,a
xo_l:     ld a,d
          out (F_SEL),a
          in a,(F_CMD)
          bit 1,a
          jr z,xo_none
          ld a,(hl)
          out (F_DAT),a
          inc hl
          ld bc,3000
          jr xo_l
xo_none:  rra
          jp nc,done_status
          dec bc
          ld a,b
          or c
          jr nz,xo_l
          jp aborted
