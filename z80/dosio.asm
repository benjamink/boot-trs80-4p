; dosio.asm -- file-writing helpers for the host, uploaded at 8000h while SERIAL/CMD runs under LS-DOS.
; The host puts a filespec (e.g. "NAME/EXT:0", ended by 0Dh) into the FCB, data into IOBUF, and
; EXECs an entry point; the monitor returns A,F,B,C,D,E,H,L as the LS-DOS call left them
; (Z = success, otherwise A = LS-DOS error number).  Calls use RST 28h with the SVC number in A
; (TRSDOS 6 Technical Reference): @INIT 58, @OPEN 59, @REMOV 57, @WRITE 75, @CLOSE 60, @EXIT 22.
; Interrupts are enabled only while LS-DOS runs; the monitor wants them off.
FCB       equ 0A000h               ; 48 bytes
IOBUF     equ 0A100h               ; 256-byte disk I/O buffer (page aligned)
PB_EOF    equ 9F02h                ; byte: EOF offset of the last record (0 = a whole record)

          org 8000h
          jp open_file             ; 8000  create (or open) FCB's file, LRL 256
          jp kill_file             ; 8003  delete the file if it exists
          jp write_rec             ; 8006  write IOBUF as the next 256-byte record
          jp close_file            ; 8009  set EOF offset from PB_EOF, close
          jp exit_dos              ; 800C  return to LS-DOS (does not return)

svc:      ei
          rst 28h
          di
          ret                      ; flags and A exactly as the SVC left them

open_file: ld hl,IOBUF
          ld de,FCB
          ld b,0                   ; LRL 0 = 256
          ld a,58
          jp svc

kill_file: ld hl,IOBUF
          ld de,FCB
          ld b,0
          ld a,59                  ; @OPEN: NZ (error 24) when the file does not exist
          call svc
          ret nz
          ld de,FCB
          ld a,57                  ; @REMOV
          jp svc

write_rec: ld hl,IOBUF
          ld de,FCB
          ld a,75
          jp svc

close_file: ld a,(PB_EOF)
          ld (FCB+8),a             ; FCB+8 = end-of-file byte offset
          ld de,FCB
          ld a,60
          jp svc

exit_dos: ld hl,0
          ld a,22
          ei
          rst 28h
          jp exit_dos
