# Assembles z80/*.asm into Intel HEX (needs sjasmplus).
build/%.hex: z80/%.asm
	@mkdir -p build
	sjasmplus --nologo --msg=err --lst=build/$*.lst --sym=build/$*.sym --hex=$@ $<

# memtest's kernel is assembled on its own (origin 9000h) and embedded in the driver, see z80/memtest_k.asm.
build/memtest_k.bin: z80/memtest_k.asm z80/memtest_march.inc z80/memtest_defs.inc
	@mkdir -p build
	sjasmplus --nologo --msg=err --raw=$@ $<

build/memtest.hex: z80/memtest.asm build/memtest_k.bin z80/memtest_march.inc z80/memtest_defs.inc
	@mkdir -p build
	sjasmplus --nologo --msg=err --lst=build/memtest.lst --sym=build/memtest.sym --hex=$@ $<

# The FujiNet client and LS-DOS commands live in fujinet/ (meant to move upstream; see fujinet/README.md).
build/%.hex: fujinet/z80/%.asm
	@mkdir -p build
	sjasmplus --nologo --msg=err -I fujinet/z80 --lst=build/$*.lst --sym=build/$*.sym --hex=$@ $<

build/fujidrv.pkg: fujinet/z80/fujidrv.asm fujinet/z80/nioclib.asm tools/make_driver.py
	python3 tools/make_driver.py $@

build/fujidrv_cmd.hex: fujinet/z80/fujidrv_cmd.asm build/fujidrv.pkg
	@mkdir -p build
	sjasmplus --nologo --msg=err -I fujinet/z80 --lst=build/fujidrv_cmd.lst --sym=build/fujidrv_cmd.sym --hex=$@ $<

build/nioboot.hex: fujinet/z80/nioboot.asm fujinet/z80/fujidrv.asm fujinet/z80/nioclib.asm
	@mkdir -p build
	sjasmplus --nologo --msg=err -I fujinet/z80 --lst=build/nioboot.lst --sym=build/nioboot.sym --hex=$@ $<

# nioboot that also makes LS-DOS run CONFIG at the end of start-up (see AUTO_CMD in nioboot.asm)
build/nioboot-config.hex: fujinet/z80/nioboot.asm fujinet/z80/fujidrv.asm fujinet/z80/nioclib.asm
	@mkdir -p build
	sjasmplus --nologo --msg=err -I fujinet/z80 '-DAUTO_CMD="CONFIG"' --lst=build/nioboot-config.lst --sym=build/nioboot-config.sym --hex=$@ $<

# Ready-made load modules for the ROM serial loader (what trs80boot.py sends); the FujiNet firmware streams them as-is.
build/%.cmd: build/%.hex tools/make_loader_cmd.py
	python3 tools/make_loader_cmd.py $< $@

all: build/nioboot.cmd build/nioboot-config.cmd build/nioclient_config.hex build/nioboot.hex build/nioboot-config.hex build/fujidrv_cmd.hex build/mon.hex build/dosio.hex build/serialcmd.hex build/nioclient.hex build/fmount.hex build/fumount.hex build/fdrive.hex build/fls.hex build/memtest.hex
clean:
	rm -rf build
.PHONY: all clean
.DELETE_ON_ERROR:
