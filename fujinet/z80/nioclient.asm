; nioclient.asm -- entry table at 8000h for the fujinet-nio client library (nioclib.asm; see there).
          org 8000h
          jp nio_exchange
          jp nio_request
          jp disk_info
          jp disk_read
          jp disk_write
          jp disk_mount
          jp disk_unmount
          jp disk_list
          jp file_list

          include "nioclib.asm"
