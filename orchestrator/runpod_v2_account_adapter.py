"""Dormant v2 -> one official account read adapter. No enrollment or GPU path.

No native read or HTTP call occurs on import/default invocation. Network use needs a
new explicit combined approval: v2 read + key sent to official RunPod + myself.id.
Only internal account ID is returned; no secret, URL, body or exception is emitted.
Python immutable strings cannot be perfectly erased; byte buffers are wiped.
"""
import http.client
import json
import re
import time
from urllib.parse import urlencode

from orchestrator.runpod_local_credential import LocalScope, RunPodLocalCredentialFlow
from orchestrator.windows_credential_store import wipe


def fetch_account_id(provider_key, *, connection_factory=None):
    """Official read-only myself query; key stays in memory, never in argv/logs."""
    if (type(provider_key) is not str or not 16 <= len(provider_key) <= 512
            or any(c.isspace() or ord(c) < 32 for c in provider_key)):
        raise RuntimeError('ACCOUNT_LOOKUP_REFUSED')
    connection = None
    try:
        # RunPod documents GraphQL authentication via api_key query parameter.
        # No browser navigation, redirects, retries, debug output or URL logging.
        connection = (connection_factory or http.client.HTTPSConnection)('api.runpod.io', timeout=10)
        connection.request('POST', '/graphql?' + urlencode({'api_key': provider_key}),
                           body=b'{"query":"query { myself { id } }"}',
                           headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError()
        raw = response.read(16385)
        if len(raw) > 16384:
            raise ValueError()
        def unique(pairs):
            value = {}
            for k, v in pairs:
                if k in value:
                    raise ValueError()
                value[k] = v
            return value
        result = json.loads(raw, object_pairs_hook=unique)
        if (type(result) is not dict or result.get('errors') or type(result.get('data')) is not dict
                or set(result['data']) != {'myself'} or type(result['data']['myself']) is not dict
                or set(result['data']['myself']) != {'id'}):
            raise ValueError()
        account = result['data']['myself']['id']
        if (type(account) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', account) is None
                or account.startswith('public-fixture')):
            raise ValueError()
        return account
    except Exception:  # noqa: BLE001 - do not relay credential-bearing HTTP exceptions
        raise RuntimeError('ACCOUNT_LOOKUP_REFUSED') from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001, S110 - never log credential-bearing HTTP details
                pass


def read_account_once(scope, *, external_read_approved=False, enabled=False,
                      flow=None, lookup=fetch_account_id, clock=time.time):
    """Trusted owner caller only; deliberately not exposed by a CLI/model tool."""
    if enabled is not True or external_read_approved is not True:
        return {"status": "disabled"}
    if type(scope) is not LocalScope:
        return {"status": "denied"}
    value = bytearray()
    credential = None
    try:
        owner = flow or RunPodLocalCredentialFlow(scope, enabled=True)
        if not owner._allowed():
            return {"status": "denied"}
        started = clock()
        value = owner._backing_store().read()
        if not owner._allowed() or clock() - started >= 10:
            return {"status": "denied"}
        credential = value.decode("utf-8")
        account = lookup(credential)
        if not owner._allowed() or clock() - started >= 10:
            return {"status": "expired"}
        return {"status": "account-verified", "account_id": account}
    except Exception:  # noqa: BLE001 - return status only, never secret-bearing details
        return {"status": "failed"}
    finally:
        credential = None
        wipe(value)
