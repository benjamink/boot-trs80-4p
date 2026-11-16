-- Driven by tools/mame4p.py. Environment: MAME4P_CTL = path prefix for the control files, MAME4P_MODE = "disk" | "serial".
--   <ctl>.cmd     commands from Python, one per line:  "keys <text>"  (\n inside the text = Enter),  "exit"
--   <ctl>.screen  the 4P's text screen, rewritten about twice a second
local m = manager.machine
local ctl = os.getenv("MAME4P_CTL")
local mode = os.getenv("MAME4P_MODE") or "disk"
local io_space = m.devices[":maincpu"].spaces["io"]
local vr = m.memory.shares[":videoram"]

local function setport(t, v) for _, f in pairs(m.ioport.ports[":rs232:pty:" .. t].fields) do f.user_value = v end end
-- the pty behaves as a 19200 baud, 8 data bits, odd parity, 1 stop bit line (the 4P's serial loader format)
setport("RS232_RXBAUD", 9); setport("RS232_TXBAUD", 9); setport("RS232_PARITY", 1)
setport("RS232_DATABITS", 3); setport("RS232_STOPBITS", 1)

local rshift
for _, f in pairs(m.ioport.ports[":LINE7"].fields) do if f.name == "Right Shift" then rshift = f end end
if mode == "serial" then rshift:set_value(1) end          -- right shift at reset: the ROM serial loader ("Ready")

local function screen_text()
  local cols = 80
  local out = {}
  for r = 0, 23 do
    local line = {}
    for c = 0, cols - 1 do
      local b = vr:read_u8(r * cols + c)
      line[#line + 1] = (b >= 32 and b < 127) and string.char(b) or " "
    end
    out[#out + 1] = (table.concat(line):gsub("%s+$", ""))
  end
  return table.concat(out, "\n")
end

local function write_file(path, text)
  local f = io.open(path .. ".tmp", "w"); f:write(text); f:close(); os.rename(path .. ".tmp", path)
end

-- MAME4P_TAP=<file>: log every byte the program writes to the UART data port (EBh) and every UART control write
local tapfile = os.getenv("MAME4P_TAP")
if tapfile then
  local tf = io.open(tapfile, "w"); tf:setvbuf("line")
  io_space:install_write_tap(0xE8, 0xEB, "uartw", function(off, data, mask)
    tf:write(string.format("W %02X %02X\n", off, data & 0xFF))
  end)
end

-- MAME runs this script again after every reset, so "already reset once" has to live in a file
local sentinel = ctl .. ".reset"
local already = io.open(sentinel, "r")
if already then already:close() end

local frames = 0
emu.register_frame_done(function()
  frames = frames + 1
  if mode == "disk" then
    -- MAME's 4P ROM samples the floppy ready line before the drive has spun up. Keep drive 0 selected so it spins;
    -- the first time round, reset once so the ROM then finds it running.
    if frames >= 60 and frames < 300 and frames % 10 == 0 then io_space:write_u8(0xF4, 0x81) end
    if frames == 300 and not already then io.open(sentinel, "w"):close(); m:soft_reset() end
  end
  if frames % 30 == 0 then
    -- the 64x16 text of the ROM's own screen is not what this reads; "screen" is meaningful once LS-DOS is up
    write_file(ctl .. ".screen", screen_text())
    local f = io.open(ctl .. ".cmd", "r")
    if f then
      local data = f:read("*a"); f:close()
      if #data > 0 then
        io.open(ctl .. ".cmd", "w"):close()
        for line in data:gmatch("[^\n]+") do
          if line == "exit" then m:exit()
          elseif line:sub(1, 5) == "keys " then m.natkeyboard:post((line:sub(6):gsub("\\n", "\n"))) end
        end
      end
    end
  end
end)
