#!/usr/bin/env bash
set -e

# =========================
# COLORS
# =========================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# =========================
# ROOT CHECK
# =========================
[[ $EUID -ne 0 ]] && log_err "Запусти через sudo -i"

# =========================
# INPUT
# =========================
read -p "Домен: " DOMAIN
[[ -z "$DOMAIN" ]] && log_err "Домен обязателен"

HTTPS_PORT=8443
BASE_DIR="/opt/vpn"

# =========================
# PORT CHECK
# =========================
log_info "Проверка портов..."
ss -tuln | grep -q ":80 " && log_err "80 занят"
ss -tuln | grep -q ":443 " && log_err "443 занят"
ss -tuln | grep -q ":$HTTPS_PORT " && log_err "$HTTPS_PORT занят"

# =========================
# DOCKER
# =========================
log_info "Docker..."
if ! command -v docker &> /dev/null; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi

# =========================
# FAIL2BAN + UFW
# =========================
log_info "Fail2Ban + UFW..."
apt update -y
apt install -y fail2ban ufw

# =========================
# UFW RULES
# =========================
log_info "UFW..."

ufw default deny incoming
ufw default allow outgoing

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw allow ${HTTPS_PORT}/tcp
ufw allow ${HTTPS_PORT}/udp
ufw allow 10000:10100/tcp
ufw allow 10000:10100/udp
ufw deny 2053/tcp
ufw deny 2096/tcp
ufw deny 2053/udp
ufw deny 2096/udp

ufw --force enable

# =========================
# DIRS
# =========================
mkdir -p $BASE_DIR/{caddy,3x-ui}
cd $BASE_DIR

# =========================
# DOCKER COMPOSE
# =========================
log_info "docker-compose..."

cat > docker-compose.yml <<EOF
services:
  3x-ui:
    image: ghcr.io/mhsanaei/3x-ui:latest
    container_name: 3x-ui
    hostname: ${DOMAIN}
    network_mode: host
    restart: unless-stopped
    volumes:
      - ./3x-ui:/etc/x-ui
    environment:
      - XRAY_VMESS_AEAD_FORCED=false
    cap_add:
      - NET_ADMIN

  caddy:
    image: caddy:2-alpine
    container_name: caddy
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./caddy/Caddyfile:/etc/caddy/Caddyfile
      - ./caddy/data:/data
      - ./caddy/config:/config
EOF

# =========================
# CADDY
# =========================
mkdir -p caddy

cat > caddy/Caddyfile <<EOF
:80 {
  redir https://{host}:${HTTPS_PORT}{uri}
}

${DOMAIN}:${HTTPS_PORT} {

  encode gzip

  log {
    output file /data/access.log
  }

  handle /Хор/* {
    reverse_proxy 127.0.0.1:2096
  }
  
  handle /json/* {
    reverse_proxy 127.0.0.1:2096
  }
  
  handle /* {
    reverse_proxy 127.0.0.1:2053
  }

  respond "404" 404
}
EOF

# =========================
# FAIL2BAN CONFIG
# =========================
log_info "Fail2Ban настройка..."

mkdir -p /etc/fail2ban/filter.d

cat > /etc/fail2ban/jail.local <<EOF
[DEFAULT]
bantime = 2h
findtime = 10m
maxretry = 5

[sshd]
enabled = true

[caddy-panel]
enabled = true
port = ${HTTPS_PORT}
filter = caddy-panel
logpath = ${BASE_DIR}/caddy/data/access.log
maxretry = 5
findtime = 10m
bantime = 3h
EOF

cat > /etc/fail2ban/filter.d/caddy-panel.conf <<EOF
[Definition]
failregex = ^.*<HOST> .* "(GET|POST) /panel.*" (401|403|404)
ignoreregex =
EOF

systemctl restart fail2ban
systemctl enable fail2ban




# =========================
# START
# =========================
log_info "Запуск..."
docker compose up -d

sleep 8

echo ""
echo "======================"
echo "ПАНЕЛЬ:"
echo "https://${DOMAIN}:${HTTPS_PORT}/"
echo "======================"
echo ""
log_warn "После запуска ОБЯЗАТЕЛЬНО задай логин/пароль в 3x-ui"
