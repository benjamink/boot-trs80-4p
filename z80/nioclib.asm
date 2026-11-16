; nioclient.asm -- fujinet-nio client for the TRS-80 Model 4P: FujiBus packets in SLIP frames over the
; UART (EAh status, EBh data), plus the DiskDevice calls an LS-DOS driver / CONFIG needs.
; Protocol: fujinet-nio docs/protocol_reference.md and docs/disk_device_protocol.md (GPL-3.0 project).
; The reference implementation of the wire format is trs80/fujibus.py + trs80/niodisk.py; the tests run this
; code in the Z80 interpreter against it.
;
; The UART must already be set up (19200 baud, 8 bits, odd parity, 1 stop): the ROM loader does it for a
; serial boot, z80/serialcmd.asm does it under LS-DOS. Interrupts are not used and should be off (di).
;
; nio_exchange   8000: A=device, B=command, DE=payload length, payload already at NIO_TX+6.
; nio_request    8003: A=device, B=command, HL=payload pointer, DE=payload length (copied to NIO_TX+6).
;     Both: CF=0 ok: A=NIO status (0 = Ok), HL=response payload, DE=its length.
;           CF=1 failed: A=1 timeout, 2 bad SLIP escape, 3 bad length/too long, 4 bad checksum, 5 unsupported
;           descriptor. Timeouts, framing errors and checksum errors are retried 3 times first (the request
;           stays in NIO_TX; DiskDevice reads and writes are idempotent).
; disk_info      8006, disk_read 8009, disk_write 800C: parameter block PB (9F00h):
;     +0 slot (1-based)   +1..+4 LBA (little endian)   +5,+6 data buffer address (read: destination of 256
;     bytes, write: source of 256 bytes)   +7 NIO status   +8 error (0 ok, 1-5 as above, 6 = NIO refused:
;     see +11, 7 = malformed answer)   +9,+10 bytes read   +11 DiskError code when error = 6
;     disk_info results: +12 flags (bit0 inserted, bit1 read-only), +13,+14 sector size, +15..+18 sector count.
; Sector size is fixed at 256 (LS-DOS).
; disk_mount 800F: slot (+0), +19 flags (bit0 = read-only), +20,21 URI address, +22,23 URI length,
;     +24,25 sector size hint (0 = let NIO decide). On success +12..+18 as for disk_info.
; file_list 8018: FileDevice ListDirectory as text lines. +20,21 URI address, +22,23 URI length, +26,27 first entry,
;     the rest as disk_list (text to +5,+6, length +9,+10, entries +29,+30, more +28).
; disk_unmount 8012: slot (+0).
; disk_list 8015: +26,27 first entry to list; text (lines "<unit>: <RO|AUTO> <uri>", unit 0-based) is copied
;     to the address in +5,+6 (room for 240 bytes), its length put in +9,+10, entries in +29,+30 and +28 = 1
;     if more follow. Errors as above.

NIO_TX    equ 0A000h               ; raw request packet, up to 0x300 bytes
NIO_RX    equ 0A300h               ; raw response packet, up to 0x300 bytes
RX_MAX    equ 0300h
PB        equ 9F00h
PAY       equ 9F20h                ; scratch for small payloads

UART_ST   equ 0EAh
UART_DATA equ 0EBh
TRIES     equ 3


; ---------------------------------------------------------------------------------------------------
nio_request:
          push af
          push bc
          push de
          ld b,d
          ld c,e
          ld a,b
          or c
          jr z,nr_go
          ld de,NIO_TX+6
          ldir                     ; payload first: the checksum covers it
nr_go:    pop de
          pop bc
          pop af
          ; fall into nio_exchange (it builds the header and checksum)

nio_exchange:
          call nio_header
nio_exchange_go:
          ld a,TRIES
          ld (v_tries),a
ne_try:   call flush_rx
          call send_packet
          call recv_packet
          ret nc
          cp 5
          scf
          ret z                    ; unsupported descriptor: retrying cannot help
          ld c,a
          ld a,(v_tries)
          dec a
          ld (v_tries),a
          ld a,c
          scf
          ret z                    ; out of tries: report the last error
          jr ne_try

; A=device, B=command, DE=payload length -> header + checksum in NIO_TX (payload bytes already there)
nio_header:
          ld hl,NIO_TX
          ld (hl),a
          inc hl
          ld (hl),b
          inc hl
          push de
          ld hl,6
          add hl,de
          ex de,hl                 ; DE = total length
          ld hl,NIO_TX+2
          ld (hl),e
          inc hl
          ld (hl),d
          inc hl
          xor a
          ld (hl),a                ; checksum byte = 0 while summing
          inc hl
          ld (hl),a                ; descriptor = 0 (no parameters)
          ld hl,NIO_TX
          ld b,d
          ld c,e
          call sum_bc              ; A = checksum of BC bytes at HL
          ld (NIO_TX+4),a
          pop de
          ret

; Sum of BC bytes at HL with the carry folded back in (FujiBus checksum). Result in A.
sum_bc:   xor a
sb1:      add a,(hl)
          adc a,0
          inc hl
          dec bc
          ld d,a                   ; keep the running sum while testing BC
          ld a,b
          or c
          ld a,d
          jr nz,sb1
          ret

; ---------------------------------------------------------------------------------------------------
flush_rx: in a,(UART_ST)
          bit 7,a
          ret z
          in a,(UART_DATA)
          jr flush_rx

; Send NIO_TX (length from its header) as one SLIP frame.
send_packet:
          ld hl,(NIO_TX+2)
          ld b,h
          ld c,l
          ld hl,NIO_TX
          ld a,0C0h
          call tx_byte
sp1:      ld a,(hl)
          inc hl
          cp 0C0h
          jr z,sp_end
          cp 0DBh
          jr z,sp_esc
          call tx_byte
sp2:      dec bc
          ld a,b
          or c
          jr nz,sp1
          ld a,0C0h
          jp tx_byte
sp_end:   ld a,0DBh
          call tx_byte
          ld a,0DCh
          call tx_byte
          jr sp2
sp_esc:   ld a,0DBh
          call tx_byte
          ld a,0DDh
          call tx_byte
          jr sp2

tx_byte:  out (UART_DATA),a
          push bc
          ld bc,120                ; ~3100 T-states: longer than one character time at 19200 baud
txd:      dec bc
          ld a,b
          or c
          jr nz,txd
          pop bc
          ret

; Receive one byte with a ~100 ms timeout. CF=1 timed out. Preserves BC.
rx_to:    push bc
          ld bc,2000h
rt1:      in a,(UART_ST)
          bit 7,a
          jr nz,rt2
          dec bc
          ld a,b
          or c
          jr nz,rt1
          pop bc
          scf
          ret
rt2:      in a,(UART_DATA)
          pop bc
          or a
          ret

; Receive one SLIP frame into NIO_RX and validate it as a FujiBus response. See the header for results.
recv_packet:
          ld e,40                  ; wait up to ~4 s for the first byte of the answer (SD card, network)
rp1:      call rx_to
          jr nc,rp2
          dec e
          jr nz,rp1
          ld a,1
          scf
          ret
rp2:      cp 0C0h
          jr nz,rp1                ; line noise before the frame
rp_start: ld hl,NIO_RX
          ld bc,0
          ld d,0                   ; D = escape pending
rp_loop:  call rx_to
          jr c,rp_timeout
          cp 0C0h
          jr z,rp_end
          ld e,a
          ld a,d
          or a
          jr nz,rp_unesc
          ld a,e
          cp 0DBh
          jr nz,rp_store
          ld d,1
          jr rp_loop
rp_unesc: ld d,0
          ld a,e
          cp 0DCh
          jr nz,rp_u1
          ld a,0C0h
          jr rp_store
rp_u1:    cp 0DDh
          jr nz,rp_badesc
          ld a,0DBh
rp_store: ld e,a
          ld a,b
          cp RX_MAX >> 8
          jr nc,rp_over
          ld (hl),e
          inc hl
          inc bc
          jr rp_loop
rp_end:   ld a,d
          or a
          jr nz,rp_badesc          ; frame ended in the middle of an escape
          ld a,b
          or c
          jr z,rp_start            ; back-to-back C0: still waiting for a real frame
          ; ---- validate: length >= 7, length field == received length, checksum, descriptor
          ld a,b
          or a
          jr nz,rp_lenok
          ld a,c
          cp 7
          jr c,rp_badlen
rp_lenok: ld hl,(NIO_RX+2)
          or a
          sbc hl,bc
          jr nz,rp_badlen
          ld a,(NIO_RX+4)
          ld (rx_ck),a             ; checksum as received
          xor a
          ld (NIO_RX+4),a          ; summed with the checksum byte zero
          push bc
          ld hl,NIO_RX
          call sum_bc
          pop bc
          ld hl,rx_ck
          cp (hl)
          jr nz,rp_badck
          ld a,(NIO_RX+5)
          cp 1                     ; exactly one 1-byte parameter: the status
          jr nz,rp_baddesc
          ld hl,-7
          add hl,bc
          ex de,hl                 ; DE = payload length
          ld hl,NIO_RX+7           ; HL = payload
          ld a,(NIO_RX+6)          ; A = NIO status
          or a                     ; CF = 0
          ret
rp_timeout: ld a,1
          scf
          ret
rp_badesc:ld a,2
          scf
          ret
rp_badlen:
rp_over:  ld a,3
          scf
          ret
rp_badck: ld a,4
          scf
          ret
rp_baddesc: ld a,5
          scf
          ret

v_tries:  db 0
rx_ck:    db 0

; ---------------------------------------------------------------------------------------------------
; DiskDevice calls (device FCh)
DEV_DISK  equ 0FCh
D_READ    equ 3
D_WRITE   equ 4
D_INFO    equ 5
D_MOUNT   equ 1
D_UNMOUNT equ 2
D_LIST    equ 0Dh
DEV_FILE  equ 0FEh
F_LISTDIR equ 2
LIST_ROOM equ 240

; common tail: CF/A from the exchange -> PB+7/+8; on success HL/DE = response payload.
; Returns A=0 (and Z) when the call succeeded and NIO said Ok; payload then still addressed by HL/DE.
disk_result:
          jr nc,dr_got
          ld (PB+8),a              ; transport error 1-5
          xor a
          ld (PB+7),a
          or 1                     ; NZ
          ret
dr_got:   ld (PB+7),a
          or a
          jr z,dr_ok
          ld a,6                   ; NIO answered with an error status
          ld (PB+8),a
          ld a,e
          cp 2
          jr c,dr_nodisk
          inc hl
          ld a,(hl)
          ld (PB+11),a             ; DiskDevice error code: payload = version, diskError
dr_nodisk: or 1
          ret
dr_ok:    xor a
          ld (PB+8),a
          ret                      ; Z

; payload head shared by read/write: version, slot, lba(4)  -> at HL; returns HL past it
disk_head:
          ld (hl),1
          inc hl
          ex de,hl
          ld hl,PB
          ld bc,5
          ldir                     ; slot + LBA
          ex de,hl
          ret

disk_info:
          ld hl,PAY
          ld (hl),1
          inc hl
          ld a,(PB)
          ld (hl),a
          ld hl,PAY
          ld de,2
          ld a,DEV_DISK
          ld b,D_INFO
          call nio_request
          call disk_result
          ret nz
          ld a,e
          cp 12                    ; version, flags, reserved(2), slot, type, size(2), count(4)
          jr nc,di_ok
          ld a,7
          ld (PB+8),a
          or a
          ret
di_ok:
di_ok_any: inc hl                  ; flags
          ld a,(hl)
          ld (PB+12),a
          ld de,PB+13
          ld bc,0
          inc hl
          inc hl
          inc hl                   ; -> type? (offsets: 0 ver, 1 flags, 2-3 rsv, 4 slot, 5 type, 6-7 size, 8-11 count)
          inc hl
          inc hl                   ; HL -> size low
          ld bc,6
          ldir                     ; size (2) + count (4) -> PB+13..+18
          xor a
          ret

disk_read:
          ld hl,PAY
          call disk_head
          ld (hl),0                ; maxBytes = 256
          inc hl
          ld (hl),1
          ld hl,PAY
          ld de,8
          ld a,DEV_DISK
          ld b,D_READ
          call nio_request
          call disk_result
          ret nz
          ; response payload: version, flags, reserved(2), slot, lba(4), dataLen(2), data...
          ld a,e
          cp 11
          jr c,dk_bad
          ld a,(hl)
          push hl
          ld bc,9
          add hl,bc
          ld c,(hl)
          inc hl
          ld b,(hl)                ; BC = dataLen
          pop hl
          ld a,b
          cp 1
          jr nz,dk_bad             ; must be exactly 256
          ld a,c
          or a
          jr nz,dk_bad
          ld de,11
          add hl,de                ; HL -> data
          ld de,(PB+5)
          ldir
          ld hl,256
          ld (PB+9),hl
          xor a
          ret
dk_bad:   ld a,7
          ld (PB+8),a
          or 1
          ret

disk_write:
          ld hl,NIO_TX+6
          call disk_head
          ld (hl),0                ; dataLen = 256
          inc hl
          ld (hl),1
          inc hl
          ex de,hl
          ld hl,(PB+5)
          ld bc,256
          ldir
          ld de,264                ; payload length: 8 + 256
          ld a,DEV_DISK
          ld b,D_WRITE
          call nio_exchange
          call disk_result
          ret

; Mount: version, slot, flags, type=0, hint(2), uriLen(2), uri
disk_mount:
          ld hl,NIO_TX+6
          ld (hl),1
          inc hl
          ld a,(PB)
          ld (hl),a
          inc hl
          ld a,(PB+19)
          and 1
          ld (hl),a
          inc hl
          ld (hl),0                ; type: auto
          inc hl
          ld a,(PB+24)
          ld (hl),a
          inc hl
          ld a,(PB+25)
          ld (hl),a
          inc hl
          ld bc,(PB+22)
          ld (hl),c
          inc hl
          ld (hl),b
          inc hl
          ex de,hl
          ld hl,(PB+20)
          ldir                     ; uri
          ld hl,(PB+22)
          ld de,8
          add hl,de
          ex de,hl                 ; DE = payload length
          ld a,DEV_DISK
          ld b,D_MOUNT
          call nio_exchange
          call disk_result
          ret nz
          jp di_ok_any

disk_unmount:
          ld hl,PAY
          ld (hl),1
          inc hl
          ld a,(PB)
          ld (hl),a
          ld hl,PAY
          ld de,2
          ld a,DEV_DISK
          ld b,D_UNMOUNT
          call nio_request
          jp disk_result

; ListMounts: version, flags=1 (text), first=0, last=0, start(2), max(2)
disk_list:
          ld hl,PAY
          ld (hl),1
          inc hl
          ld (hl),1
          inc hl
          xor a
          ld (hl),a
          inc hl
          ld (hl),a
          inc hl
          ld (hl),a
          inc hl
          ld (hl),a
          inc hl
          ld a,(PB+26)
          ld (hl),a
          inc hl
          ld a,(PB+27)
          ld (hl),a
          inc hl
          ld (hl),LIST_ROOM
          inc hl
          ld (hl),0
          ld hl,PAY
          ld de,10
          ld a,DEV_DISK
          ld b,D_LIST
          call nio_request
          call disk_result
          ret nz
          ; fall through to the text-list answer shared with file_list
list_answer:
          ; response: version, flags, first(2), start(2), count(2), len(2), text
          ld a,d
          or a
          jr nz,dl_bad
          ld a,e
          cp 10
          jr c,dl_bad
          push hl                  ; -> response start
          inc hl
          ld a,(hl)
          and 1
          ld (PB+28),a
          inc hl
          inc hl
          inc hl
          inc hl
          inc hl                   ; -> entry count
          ld a,(hl)
          ld (PB+29),a
          inc hl
          ld a,(hl)
          ld (PB+30),a
          inc hl
          ld c,(hl)
          inc hl
          ld b,(hl)                ; BC = text length
          pop hl
          ld a,b
          or a
          jr nz,dl_bad             ; more than 255 cannot be
          ld a,c
          cp LIST_ROOM+1
          jr nc,dl_bad
          ld (PB+9),bc
          ld a,e
          sub 10
          cp c
          jr c,dl_bad              ; claims more text than arrived
          ld de,10
          add hl,de
          ld de,(PB+5)
          ld a,b
          or c
          jr z,dl_empty
          ldir
dl_empty: xor a
          ret
dl_bad:   ld a,7
          ld (PB+8),a
          or 1
          ret

; FileDevice ListDirectory, formatted text: version, uriLen(2), uri, start(2), max(2), flags=4
file_list:
          ld hl,NIO_TX+6
          ld (hl),1
          inc hl
          ld bc,(PB+22)
          ld (hl),c
          inc hl
          ld (hl),b
          inc hl
          ex de,hl
          ld hl,(PB+20)
          ldir
          ex de,hl
          ld a,(PB+26)
          ld (hl),a
          inc hl
          ld a,(PB+27)
          ld (hl),a
          inc hl
          ld (hl),LIST_ROOM
          inc hl
          ld (hl),0
          inc hl
          ld (hl),4
          ld hl,(PB+22)
          ld de,8
          add hl,de
          ex de,hl
          ld a,DEV_FILE
          ld b,F_LISTDIR
          call nio_exchange
          call disk_result
          ret nz
          jp list_answer
