; mon.asm -- resident monitor for the TRS-80 Model 4P, loaded by the ROM serial loader.
; Speaks the frame protocol in trs80/frames.py. Entry 6000h. Stack 7000h (grows down).
;
; UART facts (Model 4 Technical Reference Manual; bit layout from the Model III/4 port
; reference at trs-80.com/main-internal-ports-and-i-o.htm):
;   EAh read : UART status. bit7 = Data Ready, bits 5/4/3 = overrun/framing/parity error,
;              bit6 = "Data Sent" (polarity unclear, so NOT used: we delay instead)
;   EBh      : receive holding register (read) / transmit holding register (write)
;   E8h write = UART master reset, EAh write = UART control: NEVER written here, the ROM
;   loader already configured 19200 baud, 8 data bits, odd parity.
;
; Memory: code 6000h.., variables 6C00h, RXBUF 6D00h, RESPBUF 6E00h, stack 7000h.
; Commands: 1 PING, 2 WRITE_MEM, 3 READ_MEM, 4 EXEC, 5 IN, 6 OUT. Status 0 ok, 1 bad
; checksum, 2 bad command. A repeated seq re-sends the stored response (no re-execute).
; A frame stalled for ~60 ms mid-way is abandoned and we go back to hunting for A5h.

UART_ST   equ 0EAh
UART_DATA equ 0EBh

V_CMD     equ 6C00h
V_SEQ     equ 6C01h
V_LEN     equ 6C02h
V_LASTSEQ equ 6C03h
V_HAVE    equ 6C04h
V_RST     equ 6C05h       ; status of the stored response
V_RLEN    equ 6C06h       ; payload length of the stored response
RXBUF     equ 6D00h
RESPBUF   equ 6E00h

          org 6000h

start:    di
          ld sp,7000h
          xor a
          ld (V_HAVE),a
main:     call rx_frame
          jr z,good
          ld a,(V_SEQ)             ; checksum failed: NAK, do not touch the stored response
          ld b,a
          ld c,0
          ld hl,RESPBUF
          ld a,1
          call tx_frame
          jr main
good:     ld a,(V_HAVE)
          or a
          jr z,fresh
          ld a,(V_LASTSEQ)
          ld hl,V_SEQ
          cp (hl)
          jr nz,fresh
          call send_last           ; duplicate request: repeat the stored answer
          jr main
fresh:    ld a,(V_SEQ)
          ld (V_LASTSEQ),a
          ld a,1
          ld (V_HAVE),a
          ld a,(V_CMD)
          cp 1
          jp z,c_ping
          cp 2
          jp z,c_write
          cp 3
          jp z,c_read
          cp 4
          jp z,c_exec
          cp 5
          jp z,c_in
          cp 6
          jp z,c_out
bad:      ld a,2
          ld (V_RST),a
          xor a
          ld (V_RLEN),a
reply:    call send_last
          jr main

ok_empty: xor a
          ld (V_RST),a
          ld (V_RLEN),a
          jp reply

c_ping:   ld a,(V_LEN)
          ld (V_RLEN),a
          ld c,a
          ld b,0
          ld hl,RXBUF
          ld de,RESPBUF
          call copy
          xor a
          ld (V_RST),a
          jp reply

c_write:  ld a,(V_LEN)
          sub 2
          jp c,bad
          ld c,a
          ld b,0
          ld de,(RXBUF)            ; destination address
          ld hl,RXBUF+2
          call copy
          jp ok_empty

c_read:   ld a,(V_LEN)
          cp 3
          jp nz,bad
          ld a,(RXBUF+2)           ; count
          ld (V_RLEN),a
          ld c,a
          ld b,0
          ld hl,(RXBUF)            ; source address
          ld de,RESPBUF
          call copy
          xor a
          ld (V_RST),a
          jp reply

c_exec:   ld a,(V_LEN)
          cp 2
          jp nz,bad
          ld hl,(RXBUF)
          call callhl
          push hl                  ; capture A,F,B,C,D,E,H,L into the response
          push de
          push bc
          push af
          ld hl,RESPBUF
          ld b,4
exl:      pop de                   ; D = first register, E = second
          ld (hl),d
          inc hl
          ld (hl),e
          inc hl
          djnz exl
          ld a,8
          ld (V_RLEN),a
          xor a
          ld (V_RST),a
          jp reply

callhl:   jp (hl)

c_in:     ld a,(V_LEN)
          cp 1
          jp nz,bad
          ld a,(RXBUF)
          ld c,a
          in a,(c)
          ld (RESPBUF),a
          ld a,1
          ld (V_RLEN),a
          xor a
          ld (V_RST),a
          jp reply

c_out:    ld a,(V_LEN)
          cp 2
          jp nz,bad
          ld a,(RXBUF)
          ld c,a
          ld a,(RXBUF+1)
          out (c),a
          jp ok_empty

; ---- helpers ---------------------------------------------------------------
; copy BC bytes HL -> DE; BC = 0 copies nothing (LDIR with 0 would copy 64K)
copy:     ld a,b
          or c
          ret z
          ldir
          ret

send_last: ld a,(V_LASTSEQ)
          ld b,a
          ld a,(V_RLEN)
          ld c,a
          ld hl,RESPBUF
          ld a,(V_RST)
          jp tx_frame

; A = status, B = seq, C = payload length, HL = payload. Sends 5A st seq len payload ck.
tx_frame: ld de,0                  ; DE = checksum
          push af
          ld a,5Ah
          call tx_byte
          pop af
          call tx_ck
          ld a,b
          call tx_ck
          ld a,c
          call tx_ck
          ld a,c
          or a
          jr z,tx_end
txl:      ld a,(hl)
          call tx_ck
          inc hl
          dec c
          jr nz,txl
tx_end:   ld a,e
          call tx_byte
          ld a,d
          jp tx_byte

tx_ck:    push af                  ; send A and add it into DE
          add a,e
          ld e,a
          jr nc,tc1
          inc d
tc1:      pop af
tx_byte:  out (UART_DATA),a
          push bc
          ld bc,120                ; ~3100 T-states > one character time at 19200 baud
txd:      dec bc
          ld a,b
          or c
          jr nz,txd
          pop bc
          ret

; Receive one byte, waiting forever. Returns A.
rx_wait:  in a,(UART_ST)
          bit 7,a
          jr z,rx_wait
          in a,(UART_DATA)
          ret

; Receive one byte with timeout. Carry set = timed out. Preserves BC.
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
          or a                     ; clears carry
          ret

; Receive with timeout and add into the HL checksum. Carry set = timed out.
rx_acc:   call rx_to
          ret c
          push de
          ld e,a
          ld d,0
          add hl,de
          or a                     ; the ADD may have set carry; report success
          pop de
          ret

; Receive one frame into V_CMD/V_SEQ/V_LEN/RXBUF. Returns Z if the checksum is good.
rx_frame:
hunt:     call rx_wait
          cp 0A5h
          jr nz,hunt
          ld hl,0
          call rx_acc
          jr c,hunt
          ld (V_CMD),a
          call rx_acc
          jr c,hunt
          ld (V_SEQ),a
          call rx_acc
          jr c,hunt
          ld (V_LEN),a
          ld b,a
          ld de,RXBUF
          or a
          jr z,nopl
pl:       call rx_acc
          jr c,hunt
          ld (de),a
          inc de
          djnz pl
nopl:     call rx_to               ; checksum low byte
          jr c,hunt
          ld c,a
          call rx_to               ; checksum high byte
          jr c,hunt
          ld b,a
          or a
          sbc hl,bc                ; Z if equal
          ret
