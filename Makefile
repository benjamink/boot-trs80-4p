# Assembles z80/*.asm into Intel HEX (needs sjasmplus).
build/%.hex: z80/%.asm
	@mkdir -p build
	sjasmplus --nologo --msg=err --lst=build/$*.lst --sym=build/$*.sym --hex=$@ $<

# The FujiNet client and LS-DOS commands live in fujinet/ (meant to move upstream; see fujinet/README.md).
build/%.hex: fujinet/z80/%.asm
	@mkdir -p build
	sjasmplus --nologo --msg=err -I fujinet/z80 --lst=build/$*.lst --sym=build/$*.sym --hex=$@ $<

all: build/mon.hex build/dosio.hex build/serialcmd.hex build/nioclient.hex build/fmount.hex build/fumount.hex build/fdrive.hex build/fls.hex
clean:
	rm -rf build
.PHONY: all clean
.DELETE_ON_ERROR:
