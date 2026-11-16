; FLS -- list a directory on the FujiNet's storage.   FLS [uri]      (default sd0:/)
; One line per entry as the FujiNet formats it (type, size, date, name; directories end in /).
          include "fcli.asm"

main:     ld hl,(CMDP)
          call skip_sp
          ld a,(hl)
          call at_end
          jr nz,have_uri
          ld hl,def_uri
have_uri: call word_len
          ld a,b
          or a
          jr nz,usage              ; longer than 255
          ld (PB+20),hl
          ld (PB+22),bc
          add hl,bc
          call skip_sp
          ld a,(hl)
          call at_end
          jr nz,usage              ; more than one argument
          ld de,file_list
          call list_all
          jr nc,done
          call report_file
          ld a,2
          ret
done:     push hl                  ; HL = number of entries
          call line_start
          pop hl
          push hl
          call line_dec
          pop hl
          dec hl
          ld a,h
          or l
          ld hl,m_entry            ; exactly one: "1 entry"
          jr z,plural_ok
          ld hl,m_entries
plural_ok:
          call line_add
          call line_show
          xor a
          ret
usage:    ld hl,m_usage
          call print
          ld a,1
          ret

; FileDevice failures carry NIO's status, not a DiskError
report_file:
          ld a,(PB+8)
          cp 6
          jp nz,report
          ld a,(PB+7)
          ld hl,f_notfound
          cp 5                     ; IOError: no such directory, or the storage is unreachable
          jr z,rf_show
          ld hl,f_nodev
          cp 1                     ; DeviceNotFound: no such filesystem name
          jr z,rf_show
          ld hl,f_bad
          cp 2                     ; InvalidRequest
          jr z,rf_show
          call line_start
          ld hl,f_other
          call line_add
          ld a,(PB+7)
          ld l,a
          ld h,0
          call line_dec
          ld hl,m_close
          call line_add
          jp line_show
rf_show:  jp print

def_uri:  db "sd0:/",0Dh
m_entries: db " entries",0
m_entry:  db " entry",0
m_usage:  db "Usage: FLS [uri]   (default sd0:/; e.g. host:/ or tnfs://server/dir)",0Dh
f_notfound: db "Cannot list that location: no such directory, or its storage is unreachable",0Dh
f_nodev:  db "The FujiNet does not know that kind of location (sd0:, host:, tnfs://...)",0Dh
f_bad:    db "The FujiNet rejected that location",0Dh
f_other:  db "The FujiNet refused the request (status ",0

          include "nioclib.asm"
