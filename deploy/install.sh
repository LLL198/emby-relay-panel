#!/usr/bin/env bash
set -Eeuo pipefail

# One-line bootstrap for a fresh Debian/Ubuntu controller.
# It intentionally asks for deployment-specific values instead of embedding
# domains, certificates, or Cloudflare credentials in the repository.

REPO_URL="${UNIPROXY_REPO_URL:-https://github.com/LLL198/emby-relay-panel.git}"
INSTALL_DIR="${UNIPROXY_INSTALL_DIR:-/opt/uniproxy}"
SECRET_DIR="/root/.secrets"
ENV_FILE="$SECRET_DIR/uniproxy-panel.env"
ACME_FILE="$INSTALL_DIR/acme-account.conf"
VENV="$INSTALL_DIR/.venv"
DROPIN_DIR="/etc/systemd/system/uniproxy.service.d"
DROPIN_FILE="$DROPIN_DIR/10-install.conf"

die() { echo "错误：$*" >&2; exit 1; }
warn() { echo "警告：$*" >&2; }

[[ "$(id -u)" == "0" ]] || die "请使用 root 运行，例如：curl -fsSL https://raw.githubusercontent.com/LLL198/emby-relay-panel/main/deploy/install.sh | sudo bash"
command -v bash >/dev/null 2>&1 || die "系统缺少 bash"
command -v systemctl >/dev/null 2>&1 || die "此一键脚本需要 systemd；Alpine 请按 USAGE.md 手动部署"

if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get -o DPkg::Lock::Timeout=60 update
    apt-get -o DPkg::Lock::Timeout=60 install -y \
        ca-certificates curl git openssl nginx openssh-client sshpass \
        python3 python3-pip python3-venv
elif command -v apk >/dev/null 2>&1; then
    die "检测到 Alpine；请按 USAGE.md 的 Alpine 步骤部署（当前一键脚本需要 systemd）"
else
    die "只支持 Debian/Ubuntu"
fi

if [[ -e "$INSTALL_DIR" ]]; then
    die "$INSTALL_DIR 已存在；此脚本只用于全新部署，请按 USAGE.md 手动升级或迁移"
fi
if [[ -e "$ENV_FILE" || -e /etc/systemd/system/uniproxy.service || -d /var/lib/uniproxy ]]; then
    die "检测到已有 emby-relay-panel 运行文件；为避免覆盖数据库或凭据，已停止"
fi
install -d -m 0755 "$(dirname "$INSTALL_DIR")"
git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"

cd "$INSTALL_DIR"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install aiohttp cryptography

read_tty() {
    local __name="$1" prompt="$2" value=""
    shift 2
    if [[ -r /dev/tty ]]; then
        read -r "$@" -p "$prompt" value </dev/tty || value=""
    fi
    printf -v "$__name" '%s' "$value"
}

prompt_default() {
    local __name="$1" prompt="$2" default="$3" value=""
    if [[ -n "${!__name:-}" ]]; then
        return
    fi
    if [[ -r /dev/tty ]]; then
        read -r -p "$prompt [$default]: " value </dev/tty || value=""
    fi
    printf -v "$__name" '%s' "${value:-$default}"
}

prompt_secret() {
    local __name="$1" prompt="$2" value=""
    if [[ -n "${!__name:-}" ]]; then
        return
    fi
    if [[ -r /dev/tty ]]; then
        read -r -s -p "$prompt（留空使用默认值 123456）: " value </dev/tty || value=""
        echo
    fi
    printf -v "$__name" '%s' "$value"
}

panel_domain="${PANEL_DOMAIN:-}"
node_zone="${AUTO_NODE_ZONE:-}"
admin_username="${ADMIN_USERNAME:-}"
admin_password="${ADMIN_PASSWORD:-}"
cf_token="${CF_TOKEN:-}"
tls_cert_file="${TLS_CERT_FILE:-}"
tls_key_file="${TLS_KEY_FILE:-}"

prompt_default panel_domain "主站域名" "sh.example.com"
prompt_default node_zone "Cloudflare Zone（根域名）" "example.com"
prompt_default admin_username "管理员用户名" "admin"
prompt_secret admin_password "管理员密码"
panel_domain="${panel_domain,,}"
node_zone="${node_zone,,}"

[[ "$panel_domain" =~ ^[a-z0-9]([a-z0-9-]*\.)+[a-z]{2,63}$ ]] || die "主站域名格式不正确"
[[ "$node_zone" =~ ^[a-z0-9]([a-z0-9-]*\.)+[a-z]{2,63}$ ]] || die "Cloudflare Zone 格式不正确"
[[ "$admin_username" =~ ^[A-Za-z0-9._-]+$ ]] || die "管理员用户名只能包含字母、数字、点、下划线和短横线"
[[ "$admin_password" != *$'\n'* && ${#admin_password} -le 1024 ]] || die "管理员密码包含换行或过长"

if [[ -z "$cf_token" ]]; then
    read_tty cf_token "Cloudflare API Token（可留空，之后再填）: " -s
    echo
fi
if [[ "$cf_token" == *"'"* || "$cf_token" == *$'\n'* ]]; then
    die "Cloudflare Token 不能包含单引号或换行"
fi

if [[ ! -x /root/.acme.sh/acme.sh ]]; then
    echo "正在安装 acme.sh..."
    curl -fsSL https://get.acme.sh | sh
fi
acme_bin="/root/.acme.sh/acme.sh"
mkdir -p /root/.acme.sh

custom_cert_paths=0
if [[ -n "$tls_cert_file" || -n "$tls_key_file" ]]; then
    custom_cert_paths=1
else
    tls_cert_file="/etc/letsencrypt/live/$panel_domain/fullchain.pem"
    tls_key_file="/etc/letsencrypt/live/$panel_domain/privkey.pem"
fi

if [[ "$custom_cert_paths" == "0" && -n "$cf_token" && (! -s "$tls_cert_file" || ! -s "$tls_key_file") ]]; then
    echo "正在使用 Cloudflare DNS 自动申请主站证书..."
    install -d -m 0755 "/etc/letsencrypt/live/$panel_domain"
    if CF_Token="$cf_token" "$acme_bin" --issue --dns dns_cf \
        -d "$panel_domain" --keylength ec-256 --server letsencrypt --home /root/.acme.sh; then
        if ! CF_Token="$cf_token" "$acme_bin" --install-cert -d "$panel_domain" --ecc \
            --home /root/.acme.sh \
            --fullchain-file "$tls_cert_file" --key-file "$tls_key_file" \
            --reloadcmd "systemctl reload nginx || true"; then
            warn "证书安装失败，将继续执行并保留证书路径；请检查 acme.sh 日志"
        fi
    else
        warn "主站证书自动申请失败；可以在下面手动填写已有证书路径"
    fi
fi

if [[ "$custom_cert_paths" == "0" && (! -s "$tls_cert_file" || ! -s "$tls_key_file") ]]; then
    prompt_default tls_cert_file "主站 TLS 证书路径" "$tls_cert_file"
    prompt_default tls_key_file "主站 TLS 私钥路径" "$tls_key_file"
fi
[[ "$tls_cert_file" == /* && "$tls_cert_file" != *$'\n'* ]] || die "TLS 证书路径必须是绝对路径"
[[ "$tls_key_file" == /* && "$tls_key_file" != *$'\n'* ]] || die "TLS 私钥路径必须是绝对路径"

install -d -m 0700 "$SECRET_DIR" /var/lib/uniproxy
agent_token="$($VENV/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
auth_secret="$($VENV/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
invite_key="$($VENV/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
node_key="$($VENV/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"

{
    printf 'ADMIN_USERNAME=%s\n' "$admin_username"
    if [[ -n "$admin_password" ]]; then
        printf 'ADMIN_PASSWORD=%s\n' "$admin_password"
    fi
    printf 'AGENT_TOKEN=%s\n' "$agent_token"
    printf 'INVITE_CODE_ENCRYPTION_KEY=%s\n' "$invite_key"
    printf 'NODE_CREDENTIAL_ENCRYPTION_KEY=%s\n' "$node_key"
    printf 'AUTH_THROTTLE_SECRET=%s\n' "$auth_secret"
    printf 'PANEL_DB_PATH=/var/lib/uniproxy/panel.db\n'
    printf 'TRAFFIC_LOG_PATH=/var/log/uniproxy-traffic.log\n'
    printf 'PANEL_PUBLIC_ORIGIN=https://%s\n' "$panel_domain"
    printf 'AUTO_NODE_ZONE=%s\n' "$node_zone"
    printf 'PROXY_DOMAIN_SUFFIX=%s\n' "$panel_domain"
    printf 'PUBLIC_HTTPS_PORT=443\nPUBLIC_HTTP_PORT=80\n'
    printf 'TLS_CERT_FILE=%s\nTLS_KEY_FILE=%s\n' "$tls_cert_file" "$tls_key_file"
} > "$ENV_FILE"
chown root:root "$ENV_FILE"
chmod 0600 "$ENV_FILE"

if [[ -n "$cf_token" ]]; then
    printf "SAVED_CF_Token='%s'\n" "$cf_token" > "$ACME_FILE"
    chown root:root "$ACME_FILE"
    chmod 0600 "$ACME_FILE"
else
    warn "未写入 Cloudflare Token；添加节点前请按 USAGE.md 创建 $ACME_FILE"
fi

install -m 0644 "$INSTALL_DIR/uniproxy.service" /etc/systemd/system/uniproxy.service
install -d -m 0755 "$DROPIN_DIR"
cat > "$DROPIN_FILE" <<EOF
[Service]
Environment=PROXY_DOMAIN_SUFFIX=$panel_domain
Environment=AUTO_NODE_ZONE=$node_zone
Environment=PANEL_PUBLIC_ORIGIN=https://$panel_domain
Environment=TLS_CERT_FILE=$tls_cert_file
Environment=TLS_KEY_FILE=$tls_key_file
Environment=PUBLIC_HTTPS_PORT=443
Environment=PUBLIC_HTTP_PORT=80
ExecStart=
ExecStart=$VENV/bin/python $INSTALL_DIR/uniproxy.py
EOF
chmod 0644 "$DROPIN_FILE"

systemctl daemon-reload
systemctl enable uniproxy >/dev/null
systemctl restart uniproxy

nginx_conf_dir="/etc/nginx/conf.d"
if [[ ! -d "$nginx_conf_dir" && -d /etc/nginx/http.d ]]; then
    nginx_conf_dir="/etc/nginx/http.d"
fi
install -d -m 0755 "$nginx_conf_dir"
install -m 0644 "$INSTALL_DIR/deploy/00-uniproxy-security.conf" "$nginx_conf_dir/00-emby-relay-panel-security.conf"
site_conf="$nginx_conf_dir/emby-relay-panel.conf"
if [[ ! -e "$site_conf" && -s "$tls_cert_file" && -s "$tls_key_file" ]]; then
    cat > "$site_conf" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $panel_domain;
    return 301 https://$panel_domain\$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name $panel_domain;
    ssl_certificate $tls_cert_file;
    ssl_certificate_key $tls_key_file;
    ssl_protocols TLSv1.2 TLSv1.3;
    server_tokens off;
    access_log off;

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 300s;
    }
}
EOF
    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx
    else
        rm -f "$site_conf"
        warn "自动生成的主站 Nginx 配置测试失败，已移除；请按 USAGE.md 手动配置"
    fi
elif [[ ! -s "$tls_cert_file" || ! -s "$tls_key_file" ]]; then
    warn "主站证书尚不存在，跳过 Nginx 站点配置；准备证书后按 USAGE.md 配置"
fi

echo
echo "部署初始化完成。"
echo "主站地址：https://$panel_domain"
if [[ -n "$admin_password" ]]; then
    echo "管理员密码：你刚才输入的密码"
else
    echo "管理员初始密码：123456（首次登录必须修改）"
fi
echo "下一步：登录后台添加节点；如果主站证书或 Cloudflare Token 尚未准备好，请先按 USAGE.md 完成对应步骤。"
