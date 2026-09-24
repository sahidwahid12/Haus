#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Haus - perbaiki kegagalan "git clone" di dalam container
#
# Dipakai kalau sebuah installer (mis. Hermes Agent, atau tool lain yang
# clone dari GitHub) gagal dengan gejala:
#   - "git: command not found"          (image ubuntu:22.04 polos tanpa git)
#   - "Trying SSH clone..." lalu gagal  (tidak ada ~/.ssh di container fresh)
#   - "fatal: Unable to create '.../shallow.lock': File exists"
#   - "BUG: refs/files-backend.c:..." + core dumped
#
# Pemakaian:
#   bash fix-git-clone.sh                       # default: Hermes Agent
#   bash fix-git-clone.sh /path/target          # folder tujuan lain
#   bash fix-git-clone.sh /path/target <url>    # repo lain
#
# Aman dijalankan berulang kali (idempotent).
# ---------------------------------------------------------------------------
set -u

TARGET="${1:-/usr/local/lib/hermes-agent}"
REPO="${2:-https://github.com/nousresearch/hermes-agent.git}"

echo "==> target : $TARGET"
echo "==> repo   : $REPO"

# 0) Image ubuntu:22.04 yang polos TIDAK menyertakan git - pasang dulu.
if ! command -v git >/dev/null 2>&1; then
    echo "==> [0/4] git belum terpasang, memasang git + ca-certificates ..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq || { echo "apt-get update gagal - cek koneksi"; exit 1; }
    apt-get install -y --no-install-recommends git ca-certificates \
        || { echo "pemasangan git gagal"; exit 1; }
fi
echo "==> git: $(git --version)"

# 1) Paksa HTTPS. Installer sering mencoba git@github.com: lebih dulu;
#    di container fresh tidak ada ~/.ssh, jadi pasti gagal. Dengan insteadOf
#    ini, URL SSH otomatis ditulis ulang ke HTTPS - berlaku untuk SEMUA tool,
#    bukan cuma yang sedang diinstall.
echo "==> [1/4] mengalihkan URL SSH -> HTTPS"
git config --global url."https://github.com/".insteadOf "git@github.com:"
git config --global url."https://github.com/".insteadOf "ssh://git@github.com/"

# 2) Buang checkout yang rusak DAN folder "moved aside" sisa percobaan
#    sebelumnya - dua-duanya sumber shallow.lock.
echo "==> [2/4] membersihkan sisa clone yang rusak"
rm -rf "$TARGET"
rm -rf "$TARGET".broken-*

# 3) Clone ulang dari nol ke direktori yang benar-benar kosong.
echo "==> [3/4] clone ulang (--depth 1)"
if ! git clone --depth 1 "$REPO" "$TARGET"; then
    echo
    echo "GAGAL clone. Kemungkinan:"
    echo "  - repo/URL salah      -> cek: git ls-remote $REPO"
    echo "  - jaringan terblokir  -> cek: curl -sI https://github.com"
    exit 1
fi

# 4) Laporan
echo "==> [4/4] selesai"
echo
echo "SUKSES. $TARGET berisi $(ls -A "$TARGET" | wc -l) entri:"
ls -A "$TARGET" | head -8
echo "..."
[ -d "$TARGET/.git" ] && echo ".git: ADA"
exit 0
