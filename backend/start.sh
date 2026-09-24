#!/usr/bin/env bash
# Start the Haus backend.
# The publish runtime injects PORT; fall back to 8080 for local runs.
set -u
cd "$(dirname "$0")"
PORT="${PORT:-8080}"

# Image dasar container per-user. haus-base:22.04 sudah berisi git +
# aturan rewrite SSH->HTTPS, sehingga installer tidak lagi gagal clone.
export WS_IMAGE="${WS_IMAGE:-haus-base:22.04}"

# --- Root SSH bridge (key-only) for runtime control -------------------------
# A dedicated root-access channel, SEPARATE from the per-user non-root app
# shell. The private key is exposed to authenticated accounts via
# GET /api/root-ssh so they can connect from another sandbox container.
setup_root_ssh() {
  export DEBIAN_FRONTEND=noninteractive
  local key_dir="/var/lib/webshell"
  local root_key="$key_dir/root_ssh_key"
  mkdir -p "$key_dir" /run/sshd /root/.ssh
  chmod 700 /root/.ssh
  command -v sshd >/dev/null 2>&1 || \
    { apt-get update -qq || true; apt-get install -y --no-install-recommends openssh-server >/dev/null 2>&1; } || true
  [ -f /etc/ssh/ssh_host_ed25519_key ] || \
    ssh-keygen -t ed25519 -N "" -f /etc/ssh/ssh_host_ed25519_key -q
  if [ ! -f "$root_key" ]; then
    ssh-keygen -t ed25519 -N "" -f "$root_key" -C "haus-root-bridge" -q
    chmod 600 "$root_key"
  fi
  cat "$root_key.pub" >> /root/.ssh/authorized_keys
  chmod 600 /root/.ssh/authorized_keys
  sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
  grep -q '^PermitRootLogin' /etc/ssh/sshd_config || echo 'PermitRootLogin prohibit-password' >> /etc/ssh/sshd_config
  sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
  grep -q '^PasswordAuthentication' /etc/ssh/sshd_config || echo 'PasswordAuthentication no' >> /etc/ssh/sshd_config
  /usr/sbin/sshd 2>/dev/null || true
}
setup_root_ssh

exec python3 -m uvicorn server:app --host 0.0.0.0 --port "$PORT" --log-level info
