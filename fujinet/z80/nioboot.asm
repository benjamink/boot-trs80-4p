; nioboot.asm -- boot LS-DOS from a FujiNet image instead of a floppy.
;
; Sent through the 4P ROM's serial loader (right shift at reset), entry 5000h. It does what the ROM's floppy boot does:
; reads cylinder 0 sector ID 1 into 4300h, switches the boot ROM out and jumps to 4300h. The LS-DOS boot sector then drives the
; floppy controller by itself, in one small routine at 4396h (D = cylinder, E = sector, HL = destination, A & 1Ch = 0 when ok);
; this loader overwrites that routine's first bytes with a jump to bs_read, which fetches the sector from the FujiNet instead.
; When cylinder 0 sector 15 has arrived (the last of the 16 sectors the boot sector loads to 0200h-11FFh, DCT included) bs_read
; points drive 0's DCT at the driver, so everything LS-DOS reads afterwards comes from the FujiNet too.
;
; The image is FujiNet slot 1 (drive 0). Its sectors are 256 bytes, in cylinder order, 18 per cylinder.
          org 5000h
          IFNDEF DRV_BASE
          DEFINE DRV_BASE 0E000h   ; where the driver (and its buffers) live
          ENDIF
BOOTSEC   equ 4300h
BS_READ   equ 4396h

start:    di
          ld sp,5000h
          ld a,64h                 ; UART as the ROM sets it (see fcli.asm)
          out (0EAh),a
          ld a,0FFh
          out (0E9h),a
          out (0E8h),a
          ld a,1
          ld (4055h),a             ; what the ROM leaves behind for a floppy boot: boot type 1 ...
          ld (4056h),a             ; ... and 256-byte boot sector
          ld de,1                  ; cylinder 0, sector ID 1
          ld hl,BOOTSEC
          call bs_read
          and 1Ch
          jr nz,dead
          ld a,0C3h                ; JP bs_read over the boot sector's own FDC routine
          ld (BS_READ),a
          ld hl,bs_read
          ld (BS_READ+1),hl
          xor a
          out (9Ch),a              ; boot ROM out, RAM in
          jp BOOTSEC
dead:     jr dead                  ; no FujiNet answer: stay in the ROM's screen state

; D = cylinder, E = sector, HL = destination. Preserves BC, DE, HL; returns A = 0 when read, else an LS-DOS error number.
bs_read:  push iy
          ld iy,boot_dct
          ld b,9                   ; RDSEC
          call drv_entry
          jr z,bsr_ok
          or 80h                   ; any error: set bits the boot sector tests
          jr bsr_x
bsr_ok:   ld a,e
          cp 15
          jr nz,bsr_done
          ld a,d
          or a
          jr nz,bsr_done
          ; BOOT/SYS's DCT (0470h) is in memory now: from here on drive 0 is the FujiNet (the driver's v_slot is 1).
          ; DCT+5 is left alone: LS-DOS's boot code rewrites it.
          ld hl,drv_entry
          ld (0471h),hl
bsr_done: xor a
bsr_x:    pop iy
          ret

; a stand-in DCT entry: slot 1, 40 cylinders of 18 sectors; directory cylinder 0FFh so no sector reads as a "system record"
boot_dct: db 0C3h,0,0,44h,50h,1,39,17,45h,0FFh

          include "fujidrv.asm"
