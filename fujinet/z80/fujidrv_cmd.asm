; FUJIDRV -- install the resident FujiNet disk driver on a drive.   FUJIDRV :d   (d = 1-7; drive 0 is refused)
;
; Copies the driver (build/fujidrv.pkg, made by tools/make_driver.py) just below HIGH$, lowers HIGH$ over it, relocates
; it to where it landed and points the drive's DCT at it. FMOUNT :d then attaches an image; the drive's FujiNet slot is d+1.
          org 3000h
          ld (cmdp),hl
          ld hl,(cmdp)
          call skip_sp
          ld a,(hl)
          cp ':'
          jr nz,nocolon
          inc hl
nocolon:  ld a,(hl)
          sub '0'
          jp c,usage
          cp 8
          jp nc,usage
          or a
          jp z,usage               ; drive 0 is where LS-DOS boots from
          ld (drive),a
          inc hl
          call skip_sp
          ld a,(hl)
          cp 0Dh
          jp nz,usage
          ; ---- where to put it
          ld a,100                 ; @HIGH$
          ld b,0
          ld hl,0
          rst 28h
          jp nz,fail
          ld de,(pkg+2)            ; total length
          or a
          sbc hl,de
          inc hl                   ; HL = base = high - total + 1
          ld (base),hl
          dec hl
          ld a,100
          ld b,0
          rst 28h                  ; HIGH$ := base - 1
          jp nz,fail
          ; ---- copy the image
          ld bc,(pkg)              ; image length
          ld hl,pkg+10
          ld de,(pkg+8)
          add hl,de
          add hl,de                ; skip the relocation table (count words)
          ld de,(base)
          ldir
          ; ---- relocate
          ld bc,(pkg+8)
          ld hl,pkg+10
rel_loop: ld a,b
          or c
          jr z,rel_done
          push bc
          ld e,(hl)
          inc hl
          ld d,(hl)
          inc hl
          push hl
          ld hl,(base)
          add hl,de                ; HL = address of the word inside the copy
          ld e,(hl)
          inc hl
          ld d,(hl)
          push hl
          ld hl,(base)
          add hl,de
          ex de,hl                 ; DE = relocated word
          pop hl
          ld (hl),d
          dec hl
          ld (hl),e
          pop hl
          pop bc
          dec bc
          jr rel_loop
rel_done: ; ---- this copy's FujiNet slot, in its own image
          ld hl,(base)
          ld de,(pkg+6)
          add hl,de
          ld a,(drive)
          inc a
          ld (hl),a
          ; ---- DCT
          ld a,(drive)
          ld c,a
          ld a,81                  ; @GTDCT
          rst 28h
          ld hl,(base)
          ld de,(pkg+4)
          add hl,de                ; entry address
          ld (iy+0),0C3h
          ld (iy+1),l
          ld (iy+2),h
          ld (iy+3),44h            ; double density, not write protected
          ld (iy+4),50h            ; double-density capable, alien controller
          ld (iy+5),0              ; current cylinder (LS-DOS's own bookkeeping)
          ld (iy+6),39             ; last cylinder
          ld (iy+7),17             ; sectors per cylinder - 1
          ld (iy+8),45h            ; 3 granules per track, 6 sectors per granule
          ld (iy+9),20             ; directory cylinder
          ld a,(drive)
          add a,'0'
          ld (digit),a
          ld (digit2),a
          ld hl,m_done
          call print
          ld hl,0
          jp finish
usage:    ld hl,m_usage
          call print
          ld hl,1
          jp finish
fail:     ld hl,m_fail
          call print
          ld hl,2
finish:   ld a,22                  ; @EXIT
          rst 28h
hang:     jr hang

print:    ld a,10                  ; @DSPLY
          rst 28h
          ret
skip_sp:  ld a,(hl)
          cp ' '
          ret nz
          inc hl
          jr skip_sp

cmdp:     dw 0
base:     dw 0
drive:    db 0
m_done:   db "FujiNet driver installed on :"
digit:    db "0 - now FMOUNT :"
digit2:   db "0 uri",0Dh
m_usage:  db "Usage: FUJIDRV :d   (d = drive 1-7)",0Dh
m_fail:   db "Could not reserve memory for the driver",0Dh
pkg:      incbin "../../build/fujidrv.pkg"
