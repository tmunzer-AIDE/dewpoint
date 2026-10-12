#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# A development authority, and the server certificate it signs for Compose's PostgreSQL (2b-4b M4 recovery, task 17):
# evaluation and CI only. A deployment uses its own private authority's certificate instead, in
# DEWPOINT_POSTGRES_TLS_DIR (docs/operations/deployment.md).
#
#   sh postgres/make-dev-ca.sh [directory] [extra DNS name ...]
#
# Writes ca.crt, ca.key, server.crt and server.key into the directory (deploy/compose/postgres/tls by default, which
# git ignores: never committed). The server certificate names postgres, localhost, 127.0.0.1 and any extra names. A
# rerun leaves existing files as they are: delete the directory to start over. Recovery tools trust ca.crt alone
# (sslrootcert=..., sslmode=verify-full).
set -eu

dir=${1:-$(dirname "$0")/tls}
[ $# -gt 0 ] && shift
if [ -e "$dir/server.crt" ] || [ -e "$dir/server.key" ]; then
  echo "make-dev-ca: $dir already holds a server certificate; left as it is" >&2
  exit 0
fi
mkdir -p "$dir"
umask 077
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

names="DNS:postgres,DNS:localhost,IP:127.0.0.1"
for name in "$@"; do
  names="$names,DNS:$name"
done

cat > "$work/ca.cnf" <<'EOF'
[req]
distinguished_name = dn
[dn]
[ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
EOF
cat > "$work/server.cnf" <<EOF
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = $names
EOF

openssl genrsa -out "$dir/ca.key" 3072 2>/dev/null
openssl req -x509 -new -key "$dir/ca.key" -sha256 -days 825 -subj "/CN=Dewpoint development CA" \
  -config "$work/ca.cnf" -extensions ca -out "$dir/ca.crt"
openssl genrsa -out "$dir/server.key" 3072 2>/dev/null
openssl req -new -key "$dir/server.key" -subj "/CN=postgres" -out "$work/server.csr"
openssl x509 -req -in "$work/server.csr" -CA "$dir/ca.crt" -CAkey "$dir/ca.key" -CAcreateserial \
  -CAserial "$work/ca.srl" -sha256 -days 825 -extfile "$work/server.cnf" -out "$dir/server.crt" 2>/dev/null
chmod 600 "$dir/ca.key" "$dir/server.key"
chmod 644 "$dir/ca.crt" "$dir/server.crt"
echo "make-dev-ca: wrote $dir (CA: $dir/ca.crt)"
