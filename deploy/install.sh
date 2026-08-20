#!/usr/bin/env bash
set -Eeuo pipefail

# Fresh Debian/Ubuntu controller installer.

REPO_URL="${UNIPROXY_REPO_URL:-https://github.com/LLL198/emby-relay-panel.git}"
INSTALL_DIR="${UNIPROXY_INSTALL_DIR:-/opt/uniproxy}"
VENV="$INSTALL_DIR/.venv"
ENV_FILE="/root/.secrets/uniproxy-panel.env"
ACME_FILE="$INSTALL_DIR/acme-account.conf"
ACME_HOME="/root/.acme.sh"
ACME_BIN="$ACME_HOME/acme.sh"
ACME_WEBROOT="/var/www/emby-relay-panel-acme"
DROPIN_DIR="/etc/systemd/system/uniproxy.service.d"
DROPIN_FILE="$DROPIN_DIR/10-install.conf"
RENEW_SERVICE="/etc/systemd/system/emby-panel-cert-renew.service"
RENEW_TIMER="/etc/systemd/system/emby-panel-cert-renew.timer"

die() { echo "错误：$*" >&2; exit 1; }
warn() { echo "警告：$*" >&2; }

[[ "$(id -u)" == "0" ]] || die "请使用 root 运行"
command -v systemctl >/dev/null 2>&1 || die "一键部署需要 systemd"
command -v apt-get >/dev/null 2>&1 || die "一键部署支持 Debian/Ubuntu"

export DEBIAN_FRONTEND=noninteractive
apt-get -o DPkg::Lock::Timeout=60 update
apt-get -o DPkg::Lock::Timeout=60 install -y \
    ca-certificates curl git nginx openssl openssh-client sshpass \
    python3 python3-pip python3-venv

[[ ! -e "$INSTALL_DIR" ]] || die "$INSTALL_DIR 已存在，请按 USAGE.md 的升级步骤操作"
[[ ! -e "$ENV_FILE" && ! -e /etc/systemd/system/uniproxy.service && ! -d /var/lib/uniproxy ]] \
    || die "检测到已有部署，为避免覆盖数据已停止"

install -d -m 0755 "$(dirname "$INSTALL_DIR")"
git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
cd "$INSTALL_DIR"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install aiohttp cryptography
"$VENV/bin/python" -m py_compile panel.py uniproxy.py origin_security.py

prompt_default() {
    local name="$1" prompt="$2" default="$3" value=""
    [[ -n "${!name:-}" ]] && return
    if [[ -r /dev/tty ]]; then
        read -r -p "$prompt [$default]: " value </dev/tty || value=""
    fi
    printf -v "$name" '%s' "${value:-$default}"
}

prompt_secret() {
    local name="$1" prompt="$2" value=""
    [[ -n "${!name:-}" ]] && return
    if [[ -r /dev/tty ]]; then
        read -r -s -p "$prompt（留空使用 123456）: " value </dev/tty || value=""
        echo
    fi
    printf -v "$name" '%s' "$value"
}

prompt_optional_secret() {
    local name="$1" prompt="$2" value=""
    [[ -n "${!name:-}" ]] && return
    if [[ -r /dev/tty ]]; then
        read -r -s -p "$prompt（可留空）: " value </dev/tty || value=""
        echo
    fi
    printf -v "$name" '%s' "$value"
}

panel_domain="${PANEL_DOMAIN:-}"
node_zone="${AUTO_NODE_ZONE:-}"
admin_username="${ADMIN_USERNAME:-}"
admin_password="${ADMIN_PASSWORD:-}"
cf_token="${CF_TOKEN:-}"

prompt_default panel_domain "面板域名" "panel.example.com"
prompt_default node_zone "节点域名所在的 Cloudflare 根域名" "example.com"
prompt_default admin_username "管理员用户名" "admin"
prompt_secret admin_password "管理员密码"
prompt_optional_secret cf_token "Cloudflare API Token（自动添加节点时使用）"

panel_domain="${panel_domain,,}"
node_zone="${node_zone,,}"
[[ "$panel_domain" =~ ^[a-z0-9]([a-z0-9-]*\.)+[a-z]{2,63}$ ]] || die "面板域名格式不正确"
[[ "$node_zone" =~ ^[a-z0-9]([a-z0-9-]*\.)+[a-z]{2,63}$ ]] || die "Cloudflare 根域名格式不正确"
[[ "$admin_username" =~ ^[A-Za-z0-9._-]+$ ]] || die "管理员用户名格式不正确"
[[ "$admin_password" != *$'\n'* && ${#admin_password} -le 1024 ]] || die "管理员密码包含换行或过长"
[[ "$cf_token" != *"'"* && "$cf_token" != *$'\n'* ]] || die "Cloudflare Token 格式不正确"

nginx_conf_dir="/etc/nginx/conf.d"
if [[ ! -d "$nginx_conf_dir" && -d /etc/nginx/http.d ]]; then
    nginx_conf_dir="/etc/nginx/http.d"
fi
install -d -m 0755 "$nginx_conf_dir" "$ACME_WEBROOT/.well-known/acme-challenge"
install -m 0644 "$INSTALL_DIR/deploy/00-uniproxy-security.conf" \
    "$nginx_conf_dir/00-emby-relay-panel-security.conf"

site_conf="$nginx_conf_dir/emby-relay-panel.conf"
cat > "$site_conf" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $panel_domain;

    location ^~ /.well-known/acme-challenge/ {
        root $ACME_WEBROOT;
        default_type text/plain;
        try_files \$uri =404;
    }

    location / {
        return 200 "emby-relay-panel certificate setup\n";
        add_header Content-Type text/plain;
    }
}
EOF

nginx -t
systemctl enable --now nginx >/dev/null
systemctl reload nginx

if [[ ! -x "$ACME_BIN" ]]; then
    echo "正在安装 acme.sh..."
    curl -fsSL https://get.acme.sh | sh
fi
[[ -x "$ACME_BIN" ]] || die "acme.sh 安装失败"

cert_dir="/etc/letsencrypt/live/$panel_domain"
tls_cert_file="$cert_dir/fullchain.pem"
tls_key_file="$cert_dir/privkey.pem"
install -d -m 0755 "$cert_dir"

echo "正在为 $panel_domain 申请证书..."
"$ACME_BIN" --issue -d "$panel_domain" --webroot "$ACME_WEBROOT" \
    --keylength ec-256 --server letsencrypt --home "$ACME_HOME"
"$ACME_BIN" --install-cert -d "$panel_domain" --ecc --home "$ACME_HOME" \
    --fullchain-file "$tls_cert_file" --key-file "$tls_key_file" \
    --reloadcmd "nginx -t && systemctl reload nginx"
chmod 0644 "$tls_cert_file"
chmod 0600 "$tls_key_file"

cat > "$site_conf" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $panel_domain;

    location ^~ /.well-known/acme-challenge/ {
        root $ACME_WEBROOT;
        default_type text/plain;
        try_files \$uri =404;
    }

    location / {
        return 301 https://$panel_domain\$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name $panel_domain;

    ssl_certificate $tls_cert_file;
    ssl_certificate_key $tls_key_file;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:emby_relay_panel_ssl:10m;
    ssl_session_timeout 1d;
    server_tokens off;

    client_max_body_size 8m;
    limit_conn uniproxy_ui_connections 30;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()" always;

    location ^~ /_admin {
        limit_req zone=uniproxy_admin burst=20 nodelay;
        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For "";
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Connection "";
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    location ~ ^/(login|register|logout|account/password)$ {
        limit_req zone=uniproxy_auth burst=8 nodelay;
        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For "";
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Connection "";
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For "";
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Connection "";
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
EOF
nginx -t
systemctl reload nginx

install -d -m 0700 /root/.secrets /var/lib/uniproxy
agent_token="$("$VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
auth_secret="$("$VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
invite_key="$("$VENV/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
node_key="$("$VENV/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"

{
    printf 'ADMIN_USERNAME=%s\n' "$admin_username"
    [[ -z "$admin_password" ]] || printf 'ADMIN_PASSWORD=%s\n' "$admin_password"
    printf 'AGENT_TOKEN=%s\n' "$agent_token"
    printf 'INVITE_CODE_ENCRYPTION_KEY=%s\n' "$invite_key"
    printf 'NODE_CREDENTIAL_ENCRYPTION_KEY=%s\n' "$node_key"
    printf 'AUTH_THROTTLE_SECRET=%s\n' "$auth_secret"
    printf 'PANEL_DB_PATH=/var/lib/uniproxy/panel.db\n'
    printf 'TRAFFIC_LOG_PATH=/var/log/uniproxy-traffic.log\n'
    printf 'PROXY_DOMAIN_SUFFIX=%s\n' "$panel_domain"
    printf 'AUTO_NODE_ZONE=%s\n' "$node_zone"
    printf 'PANEL_PUBLIC_ORIGIN=https://%s\n' "$panel_domain"
    printf 'TLS_CERT_FILE=%s\n' "$tls_cert_file"
    printf 'TLS_KEY_FILE=%s\n' "$tls_key_file"
    printf 'PUBLIC_HTTPS_PORT=443\nPUBLIC_HTTP_PORT=80\n'
    printf 'ALLOW_UNPROTECTED_EGRESS=1\n'
} > "$ENV_FILE"
chmod 0600 "$ENV_FILE"

if [[ -n "$cf_token" ]]; then
    printf "SAVED_CF_Token='%s'\n" "$cf_token" > "$ACME_FILE"
    chmod 0600 "$ACME_FILE"
else
    warn "未填写 Cloudflare Token；面板可正常使用，添加自动节点前再配置即可"
fi

install -m 0644 "$INSTALL_DIR/uniproxy.service" /etc/systemd/system/uniproxy.service
install -d -m 0755 "$DROPIN_DIR"
cat > "$DROPIN_FILE" <<EOF
[Service]
ExecStart=
ExecStart=$VENV/bin/python $INSTALL_DIR/uniproxy.py
EOF
chmod 0644 "$DROPIN_FILE"

cat > "$RENEW_SERVICE" <<EOF
[Unit]
Description=Renew $panel_domain certificate with acme.sh
After=network-online.target nginx.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$ACME_BIN --renew -d $panel_domain --ecc --home $ACME_HOME
SuccessExitStatus=2
Nice=10
EOF

cat > "$RENEW_TIMER" <<'EOF'
[Unit]
Description=Daily emby-relay-panel certificate renewal check

[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true
Unit=emby-panel-cert-renew.service

[Install]
WantedBy=timers.target
EOF
chmod 0644 "$RENEW_SERVICE" "$RENEW_TIMER"

systemctl daemon-reload
systemctl enable --now uniproxy emby-panel-cert-renew.timer >/dev/null
systemctl restart uniproxy

panel_ready=0
for _ in {1..15}; do
    if curl --fail --silent --show-error --max-time 5 \
        --resolve "$panel_domain:443:127.0.0.1" "https://$panel_domain/login" >/dev/null; then
        panel_ready=1
        break
    fi
    sleep 1
done
[[ "$panel_ready" == "1" ]] || die "服务已启动，但 HTTPS 登录页验证失败；请查看 journalctl -u uniproxy"

echo
echo "部署完成：https://$panel_domain"
echo "管理员账号：$admin_username"
if [[ -z "$admin_password" ]]; then
    echo "管理员初始密码：123456（首次登录后修改）"
else
    echo "管理员密码：使用刚才输入的密码"
fi
echo "下一步：登录管理后台添加节点。"
