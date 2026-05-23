#!/bin/sh
# Generate a self-signed TLS certificate for local development.
# Includes SAN (Subject Alternative Name) so Chrome accepts it.
# Idempotent — skips if certs already exist.

CERT_DIR="/certs"
CERT_FILE="$CERT_DIR/selfsigned.crt"
KEY_FILE="$CERT_DIR/selfsigned.key"

if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    echo "Certs already exist at $CERT_DIR — skipping generation."
    exit 0
fi

echo "Generating self-signed TLS certificate..."

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -subj "/CN=localhost/O=DocStore-Dev" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

echo "Certificate generated:"
echo "  $CERT_FILE"
echo "  $KEY_FILE"
