#!/bin/sh
# Populate HashiCorp Vault with application secrets on first boot.
#
# Two secret paths demonstrate the principle of least privilege:
#   secret/docstore/config  — general app credentials (DB, MinIO, etc.)
#   secret/docstore/kek     — Key Encryption Key (isolated, separate policy)
#
# In a real deployment, different services would receive tokens scoped to
# only the paths they need. Here, backend + worker get both policies
# because they perform encryption. A hypothetical reporting service would
# get only the "docstore-app" policy (DB access, no KEK).

set -e

# VAULT_ADDR and VAULT_TOKEN are set by docker-compose environment block.

echo "=== Vault init: waiting for Vault to be ready ==="
until vault status > /dev/null 2>&1; do
    sleep 1
done

echo "=== Writing general app secrets to secret/docstore/config ==="
vault kv put secret/docstore/config \
    secret_key="${SECRET_KEY}" \
    postgres_password="${POSTGRES_PASSWORD}" \
    minio_root_user="${MINIO_ROOT_USER}" \
    minio_root_password="${MINIO_ROOT_PASSWORD}" \
    redis_password="${REDIS_PASSWORD}"

echo "=== Writing KEK to separate path secret/docstore/kek ==="
vault kv put secret/docstore/kek \
    kek="${KEK}" \
    kek_version="${KEK_VERSION}"

echo "=== Creating Vault policies ==="

# Policy: read general app config
vault policy write docstore-app - <<'POLICY'
path "secret/data/docstore/config" {
  capabilities = ["read"]
}
POLICY

# Policy: read KEK (isolated from general config)
vault policy write docstore-kek - <<'POLICY'
path "secret/data/docstore/kek" {
  capabilities = ["read"]
}
POLICY

echo "=== Creating scoped app token ==="
# Backend + worker token: needs both general config AND the KEK
vault token create \
    -id="dev-app-token" \
    -policy="docstore-app" \
    -policy="docstore-kek" \
    -ttl="720h" \
    -display-name="docstore-backend" \
    -no-default-policy \
    2>/dev/null || echo "(token dev-app-token already exists, skipping)"

echo ""
echo "============================================"
echo "  Vault initialised successfully"
echo "============================================"
echo ""
echo "  Secrets layout:"
echo "    secret/docstore/config  -> DB, MinIO, Redis creds"
echo "    secret/docstore/kek     -> Key Encryption Key (isolated)"
echo ""
echo "  Policies:"
echo "    docstore-app  -> read secret/data/docstore/config"
echo "    docstore-kek  -> read secret/data/docstore/kek"
echo ""
echo "  Token 'dev-app-token' has BOTH policies"
echo "    (backend + worker need the KEK for encryption)"
echo ""
echo "  Vault UI: http://localhost:8200  (token: dev-root-token)"
echo "============================================"
