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
          DEFINE DOS_CLOCK         ; the driver fills in LS-DOS's date and time from the FujiNet (see fujidrv.asm)
          DEFINE HIGH_PTR 040Eh    ; where LS-DOS 6.3.1 keeps HIGH$; the driver lowers it below itself (see fujidrv.asm)
BOOTSEC   equ 4300h
BS_READ   equ 4396h

start:    di
          ld sp,5000h
          ld hl,banner             ; first sign of life on the screen (video RAM at 3C00h while the ROM is mapped)
          ld de,3E00h
          ld bc,banner_end-banner
          ldir
          ld a,64h                 ; UART as the ROM sets it (see fcli.asm)
          out (0EAh),a
          ld a,0FFh
          out (0E9h),a
          out (0E8h),a
          ld a,1
          ld (4055h),a             ; what the ROM leaves behind for a floppy boot: boot type 1 ...
          ld (4056h),a             ; ... and 256-byte boot sector
retry:    ld de,1                  ; cylinder 0, sector ID 1
          ld hl,BOOTSEC
          call bs_read
          and 1Ch
          jr z,ok
          ld hl,waiting            ; no FujiNet answer yet: say so, then keep trying (start fujinet-nio or move the cable)
          ld de,3E80h
          ld bc,waiting_end-waiting
          ldir
          jr retry
ok:          ld a,0C3h                ; JP bs_read over the boot sector's own FDC routine
          ld (BS_READ),a
          ld hl,bs_read
          ld (BS_READ+1),hl
          xor a
          out (9Ch),a              ; boot ROM out, RAM in
          jp BOOTSEC
banner:   db "nioboot: reading the boot sector from the FujiNet"
banner_end:
waiting:  db "Waiting for FujiNet..."
waiting_end:

; D = cylinder, E = sector, HL = destination. Preserves BC, DE, HL; returns A = 0 when read, else an LS-DOS error number.
bs_read:  push iy
          ld iy,boot_dct
          ld b,9                   ; RDSEC
          call drv_entry
          jr z,bsr_ok
          or 80h                   ; any error: set bits the boot sector tests
          jr bsr_x
bsr_ok:
          IFDEF AUTO_CMD
          ; AUTO_CMD: LS-DOS runs the command stored at offset 20h of boot-area sector 2 (what its AUTO command writes there) at
          ; the end of start-up. Put it into that sector as it passes, so the boot disk need not carry an AUTO command.
          ld a,e
          cp 2
          jr nz,bsr_noauto
          ld a,d
          or a
          jr nz,bsr_noauto
          push bc
          push de
          push hl
          ld de,20h
          add hl,de
          ex de,hl
          ld hl,auto_cmd
          ld bc,auto_cmd_end-auto_cmd
          ldir
          pop hl
          pop de
          pop bc
bsr_noauto:
          ENDIF
          ld a,e
          cp 15
          jr nz,bsr_done
          ld a,d
          or a
          jr nz,bsr_done
          ; BOOT/SYS's DCT (0470h) is in memory now: from here on drive 0 is the FujiNet (the driver's v_slot is 1).
          ; DCT+5 is left alone: LS-DOS's boot code rewrites it.
          ld hl,drv_entry
          ld (0471h),hl
          push bc                  ; the boot sector relies on BC, DE, HL surviving this routine
          push de
          push hl
          ld hl,047Ah              ; drives 1-7: disabled (DCT+0 = RET). LS-DOS probes every enabled floppy drive at the end of
          ld de,10                 ; its start-up, and on the 4P an empty drive hangs that probe (drive light on, seen on hardware).
          ld b,7                   ; FUJIDRV re-enables the drive it installs.
dis_lp:   ld (hl),0C9h
          add hl,de
          djnz dis_lp
          pop hl
          pop de
          pop bc
          push bc                  ; the FujiNet's clock gives LS-DOS its date, so it need not ask (see fujidrv.asm)
          push de
          push hl
          call clock_boot
          pop hl
          pop de
          pop bc
bsr_done: xor a
bsr_x:    pop iy
          ret

          IFDEF AUTO_CMD
auto_cmd: db AUTO_CMD,0Dh
auto_cmd_end:
          ENDIF

; a stand-in DCT entry: slot 1, 40 cylinders of 18 sectors; directory cylinder 0FFh so no sector reads as a "system record"
boot_dct: db 0C3h,0,0,44h,50h,1,39,17,45h,0FFh

          include "fujidrv.asm"
