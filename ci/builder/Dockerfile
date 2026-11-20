# The build environment for .github/workflows/release.yml: z88dk (for CONFIG/CMD), sjasmplus (the Z80 sources here),
# Python 3 (tests and image tools), git, make and the GitHub CLI. Built and pushed to ghcr.io by builder-image.yml.
# Alpine because the z88dk image is; GitHub's runner supports Alpine job containers.
# Pinned: z88dk releases after 20260601 emit more code for nio-config trs80/ (image end CED6 at 20260907, CEA7 at 20261116), which trips its
# 384-byte stack-reserve check (limit CE80). 20260105 builds the same CE76 image as the toolchain nio-config is developed with.
FROM z88dk/z88dk:20260105

ARG SJASMPLUS_VERSION=1.24.0
LABEL org.opencontainers.image.source="https://github.com/fujinet-nio/boot-trs80-4p" \
      org.opencontainers.image.description="Build tools for boot-trs80-4p: z88dk, sjasmplus, python3, gh"

RUN apk add --no-cache bash python3 git curl xz make g++ github-cli \
 && curl -fsSL "https://github.com/z00m128/sjasmplus/releases/download/v${SJASMPLUS_VERSION}/sjasmplus-${SJASMPLUS_VERSION}-src.tar.xz" | tar xJ -C /tmp \
 && make -C "/tmp/sjasmplus-${SJASMPLUS_VERSION}" -j"$(nproc)" \
 && install "/tmp/sjasmplus-${SJASMPLUS_VERSION}/sjasmplus" /usr/local/bin/sjasmplus \
 && rm -rf "/tmp/sjasmplus-${SJASMPLUS_VERSION}" \
 && sjasmplus --version | head -1 && zcc 2>&1 | head -1; git config --system --add safe.directory '*'

WORKDIR /work
CMD ["bash"]
