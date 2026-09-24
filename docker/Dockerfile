# ---------------------------------------------------------------------------
# Haus base image - pengganti ubuntu:22.04 polos.
#
# Masalah yang dicegah image ini:
#   1. ubuntu:22.04 TIDAK menyertakan git  -> installer langsung gagal
#   2. container fresh tidak punya ~/.ssh  -> "Trying SSH clone..." selalu gagal
#   3. sisa clone rusak -> shallow.lock -> git segfault (refs/files-backend.c)
#
# Build:  docker build -t haus-base:22.04 /workspace/webshell/docker
# Pakai:  WS_IMAGE=haus-base:22.04
# ---------------------------------------------------------------------------
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# git + ca-certificates: dua hal yang paling sering bikin installer gagal.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Tulis ulang URL SSH -> HTTPS di level system, supaya BERLAKU untuk semua
# user dan semua tool (bukan cuma Hermes). Ini yang bikin "Trying SSH clone..."
# tidak lagi berakhir gagal.
RUN git config --system url."https://github.com/".insteadOf "git@github.com:" \
    && git config --system url."https://github.com/".insteadOf "ssh://git@github.com/"

# Skrip perbaikan mandiri: user bisa jalankan `haus-fix-clone` kapan saja.
COPY fix-git-clone.sh /usr/local/bin/haus-fix-clone
RUN chmod +x /usr/local/bin/haus-fix-clone

CMD ["sleep", "infinity"]
