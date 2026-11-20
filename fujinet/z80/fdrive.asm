; SPDX-License-Identifier: GPL-3.0-or-later
; Copyright (C) 2026 Benjamin Krein
; FDRIVE -- show what the FujiNet has mounted.   FDRIVE
; One line per drive: "<d>: <RO|AUTO> <uri>", d = the LS-DOS drive number.
          include "fcli.asm"

main:     ld de,disk_list
          call list_all
          jr nc,fd_done
          call report
          ld a,2
          ret
fd_done:  ld a,h
          or l
          jr nz,fd_ok
          ld hl,m_none
          call print
          ld a,1
          ret
fd_ok:    xor a
          ret

m_none:   db "No FujiNet images mounted",0Dh

          include "nioclib.asm"
