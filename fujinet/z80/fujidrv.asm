; fujidrv.asm -- resident LS-DOS 6 disk driver that serves a drive from a fujinet-nio disk image over the 4P's UART.
;
; Installed by FUJIDRV/CMD (fujidrv_cmd.asm), which copies this image below HIGH$, sets v_slot and points a drive's DCT at drv_entry.
; ABI, as the LS-DOS floppy and MEMDISK drivers use it (TRSDOS 6 technical reference, "Disk I/O Table"):
;     B = function, D = cylinder, E = sector, HL = buffer, IY = the drive's DCT entry.
;     Returns Z = ok, or NZ with A = LS-DOS error number. BC, DE, HL are preserved; interrupts are as the caller had them.
; The FujiNet slot is the driver's own (v_slot, set by the installer): LS-DOS keeps rewriting DCT+5, so nothing may live there.
; Geometry comes from the DCT: DCT+6 = last cylinder, DCT+7 = sectors per cylinder - 1, DCT+9 = directory cylinder.
; Sector size is 256. LBA = cylinder * sectors-per-cylinder + sector. Single-sided only.
;
; The directory cylinder is reported the way LS-DOS expects of its own format: reading a sector there delivers the
; data and returns error 6 ("attempted to read system data record"), because FORMAT marks every sector of the
; directory cylinder with the deleted data mark. A FujiNet image carries no data marks, so this is synthesized.
;
; The image is position independent only through relocation: tools/make_driver.py assembles it twice and records every
; address word, and the installer adds the load address to each.
          IFNDEF DRV_BASE
DRV_BASE  equ 8000h
          ENDIF
          org DRV_BASE

E_RERR    equ 4                    ; parity error during read
E_DNF     equ 5                    ; data record not found during read
E_SYSREC  equ 6                    ; attempted to read system data record
E_NODEV   equ 8                    ; device not available
E_WERR    equ 12                   ; parity error during write
E_WDNF    equ 13                   ; data record not found during write
E_WPROT   equ 15                   ; write protected disk

; standard memory header (TRSDOS 6 "Memory Header"), so @GTMOD can find the module by name
mod_hdr:  jr drv_start
          dw drv_end-1             ; highest byte of memory the module uses
          db 3,"$FJ"
          dw 0                     ; MODDCB: none
          db 0
drv_start: ret                     ; nothing to initialise: the installer wires the DCT to drv_entry

; ---- driver entry ------------------------------------------------------------------------------------------
drv_entry:
          push bc
          push de
          push hl
          IFDEF HIGH_PTR           ; floppy-less boot only (nioboot.asm): HIGH$ must stay below this driver
          ld a,(HIGH_PTR+1)
          cp DRV_BASE/256
          jr c,high_ok             ; already below the driver
          ld a,DRV_BASE/256-1
          ld (HIGH_PTR+1),a
          ld a,0FFh
          ld (HIGH_PTR),a          ; HIGH$ := DRV_BASE-1
          IFDEF DOS_CLOCK
          ld a,(v_tpend)           ; armed and HIGH$ has gone back up: LS-DOS has finished initialising
          dec a
          jr nz,high_ok
          ld a,2
          ld (v_tpend),a
          ENDIF
high_ok:
          ENDIF
          ld a,i                   ; P/V = whether the caller had interrupts on
          ld a,0
          jp po,ei_off
          inc a
ei_off:   ld (v_ei),a
          di                       ; the UART has no FIFO: nothing may interrupt the exchange
          ld (v_cs),de             ; sector (E) and cylinder (D)
          ld (PB+5),hl             ; buffer
          ld a,(v_slot)
          ld (PB),a                ; FujiNet slot
          ld a,64h                 ; programmed exactly as the 4P ROM does it (see fujinet/z80/fcli.asm)
          out (0EAh),a
          ld a,0FFh
          out (0E9h),a
          out (0E8h),a
          IFDEF DOS_CLOCK
          ld a,(v_tpend)
          cp 2
          jr nz,no_time
          push bc
          call clock_time
          pop bc
no_time:
          ENDIF
          call dispatch
          pop hl
          pop de
          pop bc
          push af
          ld a,(v_ei)
          or a
          jr z,no_ei
          pop af
          ei                       ; as the caller had it
          ret
no_ei:    pop af
          ret

dispatch: ld a,b
          cp 16
          jr nc,ret_ok             ; reserved functions: harmless success
          add a,a
          ld e,a
          ld d,0
          ld hl,fn_table
          add hl,de
          ld e,(hl)
          inc hl
          ld d,(hl)
          ex de,hl
          jp (hl)

ret_ok:   xor a
          ret
f_nodev:  ld a,E_NODEV
          or a
          ret

fn_table: dw ret_ok                ; 0  DCSTAT  drive is assigned
          dw f_select              ; 1  SELECT
          dw ret_ok                ; 2  DCINIT
          dw ret_ok                ; 3  DCRES
          dw ret_ok                ; 4  RSTOR
          dw ret_ok                ; 5  STEPI
          dw ret_ok                ; 6  SEEK
          dw ret_ok                ; 7  TSTBSY  never busy
          dw ret_ok                ; 8  RDHDR
          dw f_rdsec               ; 9  RDSEC
          dw f_vrsec               ; 10 VRSEC
          dw f_rdsec               ; 11 RDTRK: no track reads, same as RDSEC
          dw f_nodev               ; 12 HDFMT
          dw f_wrsec               ; 13 WRSEC
          dw f_wrsec               ; 14 WRSYS
          dw f_nodev               ; 15 WRTRK

; ---- SELECT: is there an image on this drive? Remembered per slot until an access finds the media gone -----------
f_select: call slot_mask
          ld a,(ready_mask)
          ld hl,v_mask
          and (hl)
          jr nz,ret_ok
          call disk_info
          jr nz,sel_no
          ld a,(PB+12)
          and 1                    ; inserted
          jr z,sel_no
          ld a,(ready_mask)
          ld hl,v_mask
          or (hl)
          ld (ready_mask),a
          xor a
          ret
sel_no:   jr f_nodev

; v_mask = bit for this drive's slot (slot 1 = bit 0)
slot_mask:
          ld a,(PB)
          dec a
          and 7
          ld b,a
          ld a,1
          inc b
sm_l:     dec b
          jr z,sm_x
          add a,a
          jr sm_l
sm_x:     ld (v_mask),a
          ret

forget:   call slot_mask
          ld a,(v_mask)
          cpl
          ld hl,ready_mask
          and (hl)
          ld (hl),a
          ret

; ---- VRSEC: nothing to verify on a FujiNet image, but keep the directory cylinder's "system record" answer ------
f_vrsec:  ld a,(v_cyl)
          cp (iy+9)
          jr z,sysrec
          xor a
          ret
sysrec:   ld a,E_SYSREC
          or a
          ret

; ---- RDSEC / RDTRK ----------------------------------------------------------------------------------------
f_rdsec:  xor a
          ld (v_write),a
          call calc_lba
          ret nz
          call disk_read
          jr nz,map_err
          ld a,(v_cyl)
          cp (iy+9)
          jr z,sysrec              ; data delivered, but on the directory cylinder LS-DOS expects error 6
          xor a
          ret

; ---- WRSEC / WRSYS ----------------------------------------------------------------------------------------
f_wrsec:  ld a,1
          ld (v_write),a
          bit 7,(iy+3)             ; software write protect (SYSTEM (DRIVE=n,WP))
          jr z,wr_go
          ld a,E_WPROT
          or a
          ret
wr_go:    call calc_lba
          ret nz
          call disk_write
          ret z
          jr map_err

; ---- LBA from cylinder and sector, with range checks -----------------------------------------------------
calc_lba: ld a,(iy+6)              ; last cylinder
          ld b,a
          ld a,(v_cyl)
          cp b
          jr z,cl_cyl
          jr nc,cl_bad
cl_cyl:   ld a,(iy+7)
          and 1Fh
          inc a
          ld c,a                   ; sectors per cylinder
          ld a,(v_sec)
          cp c
          jr nc,cl_bad
          ld hl,0
          ld a,(v_cyl)
          or a
          jr z,cl_add
          ld b,a
          ld e,c
          ld d,0
cl_mul:   add hl,de
          djnz cl_mul
cl_add:   ld a,(v_sec)
          ld e,a
          ld d,0
          add hl,de
          ld (PB+1),hl
          ld hl,0
          ld (PB+3),hl
          xor a
          ret
cl_bad:   ld a,(v_write)
          or a
          ld a,E_DNF
          jr z,cl_x
          ld a,E_WDNF
cl_x:     or a
          ret

; ---- NIO failure -> LS-DOS error number --------------------------------------------------------------------
map_err:  ld a,(PB+8)
          cp 6
          jr nz,me_io              ; transport trouble
          ld a,(PB+11)             ; DiskError
          cp 10                    ; NotMounted
          jr z,me_nomount
          cp 12                    ; OutOfRange
          jr z,me_range
          cp 11                    ; ReadOnly
          jr nz,me_io
          ld a,E_WPROT
          or a
          ret
me_nomount:
          call forget
          jp f_nodev
me_range: ld a,(v_write)
          or a
          ld a,E_DNF
          jr z,me_x
          ld a,E_WDNF
          jr me_x
me_io:    ld a,(v_write)
          or a
          ld a,E_RERR
          jr z,me_x
          ld a,E_WERR
me_x:     or a
          ret

          IFDEF DOS_CLOCK
; Floppy-less boot only (nioboot.asm): LS-DOS asks for the date and time at boot, and the FujiNet has a clock. What SYS0's
; initialisation does (read from its disassembly, confirmed in MAME):
;   - it takes the date from DOS_YEAR.. (year-1900, day, month) and skips the date prompt when that is valid;
;   - it skips the time prompt when the flag byte DOS_TFLAG is nonzero, but first overwrites the time at DOS_SEC.. (sec, min,
;     hour) with its own default, after the last disk read, and sets HIGH$ (HIGH_PTR, 0000 until then).
; So clock_boot (called by nioboot when the last boot sector is in, before SYS0 loads) stores the date and the flag and arms
; v_tpend; the first driver call after that which finds HIGH$ back up (see drv_entry) calls clock_time, which stores the time.
; The FujiNet's clock device is 0x45, command 3 (GetTimeFormat), format 0 (simple): the answer is version, format, century,
; year, month, day, hour, minute, second. At most three requests in all, so with no clock device the prompts simply appear.
DOS_SEC   equ 002Dh
DOS_YEAR  equ 0033h
DOS_TFLAG equ 04C3h

clock_boot:
          call clock_get
          ret c
          ld a,(v_ck+5)
          ld (DOS_YEAR),a
          ld a,(v_ck+3)
          ld (DOS_YEAR+1),a
          ld a,(v_ck+4)
          ld (DOS_YEAR+2),a
          ld a,1
          ld (DOS_TFLAG),a
          ld (v_tpend),a           ; armed
          ret

clock_time:
          xor a
          ld (v_tpend),a           ; one try
          call clock_get
          ret c
          ld hl,v_ck
          ld de,DOS_SEC
          ld bc,3
          ldir
          ret

; CF=0: v_ck = second, minute, hour, day, month, year-1900.  CF=1: no answer.
clock_get:
          ld a,(v_clk)
          or a
          scf
          ret z
          dec a
          ld (v_clk),a
          ld hl,clk_req
          ld de,3
          ld a,45h
          ld b,3
          call nio_request
          ret c
          or a
          jr nz,cg_bad             ; NIO status not Ok
          ld a,d
          or a
          jr nz,cg_bad
          ld a,e
          cp 9
          jr c,cg_bad              ; shorter than the simple format
          inc hl
          inc hl                   ; HL -> century
          ld a,(hl)
          sub 19
          jr c,cg_bad
          ld b,a
          inc hl
          ld a,(hl)                ; year within century
          inc hl
          inc b
          jr cg_t
cg_l:     add a,100
cg_t:     djnz cg_l                ; + 100 per century after 1900
          ld (v_ck+5),a
          ld de,v_ck+4
          ld b,5
cg_c:     ld a,(hl)                ; month, day, hour, minute, second
          ld (de),a
          inc hl
          dec de
          djnz cg_c
          or a
          ret
cg_bad:   scf
          ret
clk_req:  db 1,0,0                 ; protocol version 1, simple format, no timezone override
v_clk:    db 3                     ; requests left
v_tpend:  db 0                     ; 0 = nothing to do, 1 = armed, 2 = LS-DOS has finished initialising: set the time now
v_ck:     ds 6
          ENDIF

; ---- state ------------------------------------------------------------------------------------------------
v_cs:     dw 0
v_sec     equ v_cs
v_cyl     equ v_cs+1
v_write:  db 0
v_mask:   db 0
v_ei:     db 0
v_slot:   db 1                     ; FujiNet slot this copy of the driver serves; FUJIDRV writes it after copying
ready_mask: db 0

; ---- the FujiNet client, with its buffers placed after the image ------------------------------------------
          DEFINE NIO_EXTERNAL
NIO_TX    equ bss
NIO_RX    equ bss+0130h
RX_MAX    equ 0200h
PB        equ NIO_RX+0200h
PAY       equ PB+32
drv_end   equ PAY+32
          include "nioclib.asm"
bss       equ $
