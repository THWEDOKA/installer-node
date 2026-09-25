#!/usr/bin/env bash
set -Eeuo pipefail
: "${LANGUAGE_CHOICE:=en}"
say() { if [[ "$LANGUAGE_CHOICE" == ru ]]; then printf '%s\n' "$1"; else printf '%s\n' "$2"; fi; }
if (( EUID != 0 )); then say 'Запустите от root.' 'Run as root.' >&2; exit 1; fi
. /etc/os-release
case "$ID" in ubuntu|debian) ;; *) say 'WARP поддерживает только Ubuntu и Debian.' 'WARP supports Ubuntu and Debian only.' >&2; exit 1;; esac
if ! command -v warp-cli >/dev/null; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y curl gpg ca-certificates lsb-release
  curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --dearmor > /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
  printf 'deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ %s main\n' "$(lsb_release -cs)" > /etc/apt/sources.list.d/cloudflare-client.list
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y cloudflare-warp
fi
if ! warp-cli --accept-tos registration show >/dev/null 2>&1; then warp-cli --accept-tos registration new; fi
warp-cli --accept-tos disconnect >/dev/null 2>&1 || true
warp-cli --accept-tos mode proxy
warp-cli --accept-tos proxy port 40000
warp-cli --accept-tos connect
for _ in {1..15}; do
  if curl -fsS --connect-timeout 2 --max-time 5 --proxy socks5h://127.0.0.1:40000 https://www.cloudflare.com/cdn-cgi/trace | grep -Eq '^warp=(on|plus)$'; then
    say 'WARP работает через 127.0.0.1:40000.' 'WARP works through 127.0.0.1:40000.'
    exit 0
  fi
  sleep 2
done
say 'WARP не подтвердил соединение; профиль в панели пока не будет создан.' 'WARP connection was not verified; the panel profile will not be created yet.' >&2
exit 1
