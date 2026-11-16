; FUMOUNT -- release a drive's FujiNet image.   FUMOUNT :d
          include "fcli.asm"

main:     ld hl,(CMDP)
          call parse_drive
          jr c,usage
          ld (drive),a
          inc a
          ld (PB),a
          call skip_sp
          ld a,(hl)
          call at_end
          jr nz,usage              ; something after the drive
          call disk_unmount
          jr z,done
          call report
          ld a,2
          ret
done:     call line_start
          ld hl,m_done
          call line_add
          ld a,(drive)
          add a,'0'
          ld (digit),a
          ld hl,digit
          call line_add
          call line_show
          xor a
          ret
usage:    ld hl,m_usage
          call print
          ld a,1
          ret

drive:    db 0
digit:    db 0,0
m_done:   db "Unmounted :",0
m_usage:  db "Usage: FUMOUNT :d   (d = drive 0-7)",0Dh

          include "nioclib.asm"
