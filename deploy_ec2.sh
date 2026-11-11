#!/usr/bin/env bash
# ==============================================================================
#  PetCare — Script de Despliegue Automatizado en AWS EC2 (Ubuntu Server 22.04/24.04)
#  Arquitectura: Nginx (Puerto 80) -> Unix Socket -> Gunicorn -> Django 5.2 -> PostgreSQL
#
#  Uso:
#      chmod +x deploy_ec2.sh
#      sudo ./deploy_ec2.sh
# ==============================================================================

set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive

# ─── Parámetros configurables (sobreescribibles por variables de entorno) ────
APP_NAME="petcare"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
APP_USER="${APP_USER:-${SUDO_USER:-ubuntu}}"
APP_GROUP="www-data"
VENV_DIR="${PROJECT_DIR}/.venv"
STATIC_ROOT_DIR="/var/www/${APP_NAME}/static"
MEDIA_ROOT_DIR="/var/www/${APP_NAME}/media"
SOCKET_PATH="/run/gunicorn/${APP_NAME}.sock"

DB_NAME="${DB_NAME:-petcare}"
DB_USER="${DB_USER:-petcare_user}"
DB_PASSWORD="${DB_PASSWORD:-$(openssl rand -hex 16)}"

echo "=================================================================="
echo " 🚀 Iniciando despliegue productivo de PetCare en AWS EC2"
echo " 📁 Directorio del proyecto : ${PROJECT_DIR}"
echo " 👤 Usuario de ejecución    : ${APP_USER}"
echo "=================================================================="

# ─── 1. Instalación no interactiva de paquetes del sistema ───────────────────
echo "[1/7] Actualizando repositorios e instalando PostgreSQL, Python3-venv y Nginx..."
apt-get update -y -q
apt-get install -y -q \
  python3 \
  python3-venv \
  python3-pip \
  python3-dev \
  build-essential \
  libpq-dev \
  postgresql \
  postgresql-contrib \
  nginx \
  curl \
  openssl

systemctl enable --now postgresql
systemctl enable --now nginx

# ─── 2. Configuración de PostgreSQL, usuario, permisos y btree_gist ──────────
echo "[2/7] Configurando base de datos PostgreSQL (${DB_NAME}) y extensión btree_gist..."
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${DB_USER}') THEN
        CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';
    ELSE
        ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';
    END IF;
END
\$\$;

ALTER ROLE ${DB_USER} SET client_encoding TO 'utf8';
ALTER ROLE ${DB_USER} SET default_transaction_isolation TO 'read committed';
ALTER ROLE ${DB_USER} SET timezone TO 'America/Santiago';

SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\gexec

GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
SQL

sudo -u postgres psql -d "${DB_NAME}" -v ON_ERROR_STOP=1 <<SQL
CREATE EXTENSION IF NOT EXISTS btree_gist;
GRANT ALL ON SCHEMA public TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO ${DB_USER};
SQL

# ─── 3. Detección de IP Pública EC2 (IMDSv2) y generación de .env ────────────
echo "[3/7] Detectando IP pública de AWS EC2 y generando archivo .env..."
IMDS_TOKEN="$(curl -s -f -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 60" || true)"

if [[ -n "${IMDS_TOKEN}" ]]; then
  EC2_PUBLIC_IP="$(curl -s -f -H "X-aws-ec2-metadata-token: ${IMDS_TOKEN}" \
    "http://169.254.169.254/latest/meta-data/public-ipv4" || true)"
  EC2_PUBLIC_DNS="$(curl -s -f -H "X-aws-ec2-metadata-token: ${IMDS_TOKEN}" \
    "http://169.254.169.254/latest/meta-data/public-hostname" || true)"
else
  EC2_PUBLIC_IP=""
  EC2_PUBLIC_DNS=""
fi

LOCAL_IP="$(hostname -I | awk '{print $1}')"
ALLOWED_HOSTS_LIST="localhost,127.0.0.1,${LOCAL_IP}"
CSRF_ORIGINS_LIST="http://localhost,http://127.0.0.1,http://${LOCAL_IP}"

if [[ -n "${EC2_PUBLIC_IP}" ]]; then
  ALLOWED_HOSTS_LIST="${ALLOWED_HOSTS_LIST},${EC2_PUBLIC_IP}"
  CSRF_ORIGINS_LIST="${CSRF_ORIGINS_LIST},http://${EC2_PUBLIC_IP}"
fi
if [[ -n "${EC2_PUBLIC_DNS}" ]]; then
  ALLOWED_HOSTS_LIST="${ALLOWED_HOSTS_LIST},${EC2_PUBLIC_DNS}"
  CSRF_ORIGINS_LIST="${CSRF_ORIGINS_LIST},http://${EC2_PUBLIC_DNS}"
fi

DJANGO_SECRET_KEY="$(openssl rand -base64 48 | tr -dc 'a-zA-Z0-9!@#%^&*(-_=+)' | head -c 56)"

cat > "${PROJECT_DIR}/.env" <<EOF
SECRET_KEY=${DJANGO_SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=${ALLOWED_HOSTS_LIST}

DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
DB_HOST=localhost
DB_PORT=5432
DB_CONN_MAX_AGE=60

SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_HSTS_SECONDS=0

CSRF_TRUSTED_ORIGINS=${CSRF_ORIGINS_LIST}
CORS_ALLOWED_ORIGINS=${CSRF_ORIGINS_LIST}

SESSION_COOKIE_AGE=28800
STATIC_ROOT=${STATIC_ROOT_DIR}
MEDIA_ROOT=${MEDIA_ROOT_DIR}
LOG_LEVEL=INFO
EOF

chown "${APP_USER}:${APP_GROUP}" "${PROJECT_DIR}/.env"
chmod 640 "${PROJECT_DIR}/.env"

# ─── 4. Entorno virtual, dependencias, migraciones y estáticos ───────────────
echo "[4/7] Configurando entorno virtual Python e instalando dependencias..."
mkdir -p "${STATIC_ROOT_DIR}" "${MEDIA_ROOT_DIR}"
chown -R "${APP_USER}:${APP_GROUP}" "${PROJECT_DIR}" "${STATIC_ROOT_DIR}" "${MEDIA_ROOT_DIR}"

sudo -u "${APP_USER}" python3 -m venv "${VENV_DIR}"
sudo -u "${APP_USER}" "${VENV_DIR}/bin/pip" install --upgrade pip wheel
sudo -u "${APP_USER}" "${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"

echo "[5/7] Ejecutando migrate, seed_petcare, actualizar_vacunas_vencidas y collectstatic..."
cd "${PROJECT_DIR}"
sudo -u "${APP_USER}" "${VENV_DIR}/bin/python" manage.py migrate --noinput
sudo -u "${APP_USER}" "${VENV_DIR}/bin/python" manage.py seed_petcare
sudo -u "${APP_USER}" "${VENV_DIR}/bin/python" manage.py actualizar_vacunas_vencidas
sudo -u "${APP_USER}" "${VENV_DIR}/bin/python" manage.py collectstatic --noinput --clear

# ─── 5. Servicio systemd de Gunicorn (/etc/systemd/system/gunicorn.service) ─
echo "[6/7] Configurando Gunicorn como servicio systemd..."
cat > /etc/systemd/system/gunicorn.service <<EOF
[Unit]
Description=Gunicorn daemon for PetCare Veterinary System
After=network.target postgresql.service
Requires=postgresql.service

[Service]
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${PROJECT_DIR}/.env
RuntimeDirectory=gunicorn
ExecStart=${VENV_DIR}/bin/gunicorn \\
    --access-logfile - \\
    --error-logfile - \\
    --workers 3 \\
    --bind unix:${SOCKET_PATH} \\
    --timeout 60 \\
    config.wsgi:application
ExecReload=/bin/kill -s HUP \$MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable gunicorn.service
systemctl restart gunicorn.service

# ─── 6. Configuración de Nginx como Reverse Proxy en el Puerto 80 ────────────
echo "[7/7] Configurando Nginx como Reverse Proxy y servidor de estáticos..."
cat > "/etc/nginx/sites-available/${APP_NAME}" <<EOF
server {
    listen 80;
    server_name _;

    client_max_body_size 20M;

    # Archivos estáticos recolectados con collectstatic
    location /static/ {
        alias ${STATIC_ROOT_DIR}/;
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    # Archivos multimedia subidos por usuarios
    location /media/ {
        alias ${MEDIA_ROOT_DIR}/;
        expires 7d;
        access_log off;
    }

    # Proxy inverso hacia Gunicorn vía socket Unix
    location / {
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_redirect off;
        proxy_pass http://unix:${SOCKET_PATH};
    }
}
EOF

ln -sf "/etc/nginx/sites-available/${APP_NAME}" "/etc/nginx/sites-enabled/${APP_NAME}"
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl restart nginx

echo "=================================================================="
echo " ✅ Despliegue de PetCare finalizado exitosamente"
echo " 🌐 URL Pública EC2 : http://${EC2_PUBLIC_IP:-${LOCAL_IP}}/"
echo " 🔐 Panel Admin     : http://${EC2_PUBLIC_IP:-${LOCAL_IP}}/admin/"
echo " 👤 Credenciales    : admin / dra.morales / recepcion (Clave: PetCare2026!)"
echo "=================================================================="
