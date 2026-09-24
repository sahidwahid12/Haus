#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Haus - banner sambutan di terminal
#
#   haus-banner        tampilkan banner
#   haus-banner on     tampilkan otomatis setiap kali login
#   haus-banner off    sembunyikan saat login (bisa dipanggil lagi kapan saja)
#
# Banner ini hanya milik container kamu. Menyembunyikannya tidak menghapus
# apa pun - cukup menandai supaya tidak dicetak saat shell dibuka.
# ---------------------------------------------------------------------------
FLAG="$HOME/.haus_banner_off"

case "${1:-}" in
    on)
        rm -f "$FLAG"
        echo "Banner akan ditampilkan lagi saat login."
        exit 0
        ;;
    off)
        touch "$FLAG"
        echo "Banner disembunyikan. Ketik: haus-banner   untuk melihatnya lagi."
        exit 0
        ;;
esac

G='\033[38;5;46m'   # hijau Haus
C='\033[38;5;81m'   # cyan
D='\033[38;5;245m'  # abu-abu
R='\033[0m'

printf "${G}"
cat <<'ART'
  ██╗  ██╗ █████╗ ██╗   ██╗███████╗
  ██║  ██║██╔══██╗██║   ██║██╔════╝
  ███████║███████║██║   ██║███████╗
  ██╔══██║██╔══██║██║   ██║╚════██║
  ██║  ██║██║  ██║╚██████╔╝███████║
  ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝
ART
printf "${R}"

printf "${C}Haus${R} ${D}- terminal Linux pribadimu, aktif 24/7.${R}\n"
echo
cat <<'TXT'
  • Container ini MILIKMU sendiri dan tetap hidup walau HP mati.
  • Setiap akun punya container terpisah (file & proses tidak terlihat user lain).
  • Batas: 2 GB RAM, 1 CPU.

  Tombol di bawah layar: ESC  TAB  CTRL  ALT  panah  ENTER  / | ~ . , * -

  Perintah:
    haus-banner        tampilkan banner ini lagi
    haus-banner off    sembunyikan saat login
    haus-banner on     tampilkan lagi saat login

  Tips:
    apt-get update && apt-get install -y <paket>    pasang paket
    haus-fix-clone                                  perbaiki gagal clone git
    9Router Dashboard                                jalankan di port 20128

  Setelah 9Router aktif di 0.0.0.0:20128, tekan tombol "Open Web UI" di aplikasi Haus.
TXT
echo
