"""Optional HashiCorp Vault integration for secrets management.

When VAULT_ADDR and VAULT_TOKEN are set, secrets are read from Vault's
KV v2 engine. When unset, the module is a no-op and callers fall through
to their existing env-var / config paths.
"""

from __future__ import annotations

import os

from app.logging_config import get_logger

log = get_logger(__name__)

_client = None
_client_checked = False


def get_vault_client():
    """Return a configured hvac.Client, or None if Vault is not configured."""
    global _client, _client_checked
    if _client_checked:
        return _client

    _client_checked = True

    vault_addr = os.environ.get("VAULT_ADDR", "")
    vault_token = os.environ.get("VAULT_TOKEN", "")

    if not vault_addr or not vault_token:
        log.info("vault.disabled", message="VAULT_ADDR or VAULT_TOKEN not set; using env vars")
        return None

    try:
        import hvac
    except ImportError:
        log.warning("vault.hvac_missing", message="hvac package not installed; using env vars")
        return None

    client = hvac.Client(url=vault_addr, token=vault_token)
    try:
        client.secrets.kv.v2.read_secret_version(
            path="docstore/config", raise_on_deleted_version=True
        )
    except Exception as exc:
        log.warning("vault.auth_failed", message=f"Vault probe failed: {exc}")
        return None

    log.info("vault.connected", addr=vault_addr)
    _client = client
    return _client


def read_secret(path: str, key: str) -> str | None:
    """Read a single key from a Vault KV v2 path. Returns None on failure."""
    client = get_vault_client()
    if client is None:
        return None
    try:
        result = client.secrets.kv.v2.read_secret_version(
            path=path, raise_on_deleted_version=True
        )
        return result["data"]["data"].get(key)
    except Exception as exc:
        log.warning("vault.read_failed", path=path, key=key, error=str(exc))
        return None


def reset_vault_cache() -> None:
    """For tests: drop the cached client so the next call re-checks."""
    global _client, _client_checked
    _client = None
    _client_checked = False
