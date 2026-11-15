# Assembles z80/*.asm into Intel HEX (needs sjasmplus).
build/%.hex: z80/%.asm
	@mkdir -p build
	sjasmplus --nologo --msg=err --lst=build/$*.lst --sym=build/$*.sym --hex=$@ $<

all: build/mon.hex
clean:
	rm -rf build
.PHONY: all clean
.DELETE_ON_ERROR:
