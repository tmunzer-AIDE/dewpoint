# SPDX-License-Identifier: Apache-2.0
import httpx

from dewpoint.core.connections.types import MIST_CLOUDS, MistConfig, MistSecret, VerifyResult


async def verify_mist(config: MistConfig, secret: MistSecret, http: httpx.AsyncClient) -> VerifyResult:
    base = f"https://{MIST_CLOUDS[config.cloud]}/api/v1"  # host from allowlist only
    headers = {"Authorization": f"Token {secret.api_token.get_secret_value()}", "Accept": "application/json"}
    try:
        r = await http.get(f"{base}/self", headers=headers, follow_redirects=False, timeout=10)
        if r.status_code in (401, 403):
            return VerifyResult(False, "invalid_token")
        if r.status_code != 200:
            return VerifyResult(False, "unexpected_status")
        privileges = r.json().get("privileges", [])
        for p in privileges:
            if p.get("scope") == "org" and p.get("org_id") == str(config.org_id):
                return VerifyResult(True, "ok", str(p.get("role")))
        if any(p.get("scope") == "msp" for p in privileges):
            o = await http.get(f"{base}/orgs/{config.org_id}", headers=headers, follow_redirects=False, timeout=10)
            if o.status_code == 200:
                return VerifyResult(True, "ok", "msp")
        return VerifyResult(False, "no_org_access")
    except (httpx.HTTPError, ValueError):
        return VerifyResult(False, "unreachable")
