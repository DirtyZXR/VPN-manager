# 3x-ui API Migration: Old Implementation vs v3.1.0

## Critical Breaking Changes

### 1. Login: form-data → JSON body

**File:** `app/xui_client/client.py:228-230`

| Aspect | Old (current code) | New (v3.1.0) |
|---|---|---|
| Content-Type | `application/x-www-form-urlencoded` (aiohttp `data=`) | `application/json` |
| Body format | `data={"username": ..., "password": ...}` | `json={"username": ..., "password": ..., "twoFactorCode": "..."}` |
| 2FA support | Not supported | `twoFactorCode` field (optional) |

**Fix:** Change `session.post(url, data={...})` to `session.post(url, json={...})` and add `twoFactorCode` support.

---

### 2. Client management: inbound-embedded → first-class Clients API

This is the **largest breaking change**. In v3.1.0, clients are standalone entities with their own REST endpoints under `/panel/api/clients/`. They are no longer managed exclusively as nested JSON inside inbound `settings`.

#### 2a. Add client

**File:** `app/xui_client/client.py:340-374`

| Aspect | Old | New |
|---|---|---|
| Endpoint | `POST /panel/api/inbounds/addClient` | `POST /panel/api/clients/add` |
| Content-Type | form-encoded (`data=`) | JSON (`json=`) |
| Body | `{"id": "<inbound_id>", "settings": "<JSON string with clients[]>"}` | `{"client": {...fields...}, "inboundIds": [3, 5]}` |
| Client ID | Caller generates UUID | Server auto-generates UUID (can still provide `id`) |
| Multi-inbound | Not supported — one inbound at a time | Attach to multiple inbounds in a single call |

**Old request body:**
```python
data={
    "id": str(inbound_id),
    "settings": json.dumps({
        "clients": [client.model_dump()],
        "decryption": "none",
        "fallbacks": [],
    })
}
```

**New request body:**
```python
json={
    "client": {
        "email": "alice@example.com",
        "totalGB": 53687091200,
        "expiryTime": 1735689600000,
        "enable": True,
    },
    "inboundIds": [3, 5]
}
```

#### 2b. Update client

**File:** `app/xui_client/client.py:376-409`

| Aspect | Old | New |
|---|---|---|
| Endpoint | `POST /panel/api/inbounds/updateClient/{client_uuid}` | `POST /panel/api/clients/update/{email}` |
| Identifier | Client UUID | Client **email** |
| Content-Type | form-encoded | JSON |
| Scope | Single inbound | Propagates to **all** attached inbounds |

#### 2c. Delete client

**File:** `app/xui_client/client.py:411-437`

| Aspect | Old | New |
|---|---|---|
| Endpoint | `POST /panel/api/inbounds/{inbound_id}/delClient/{client_uuid}` | `POST /panel/api/clients/del/{email}` |
| Identifier | inbound_id + client_uuid | Client **email** |
| Scope | Single inbound | Removes from **all** attached inbounds |
| New option | — | `?keepTraffic=1` query param to preserve traffic data |

#### 2d. Get clients / traffic

**File:** `app/xui_client/client.py:323-338` and `515-541`

| Aspect | Old | New |
|---|---|---|
| List clients | `GET /panel/api/inbounds/getClientTraffics/{inbound_id}` (undocumented, may still work) | `GET /panel/api/clients/list` (all clients) or `GET /panel/api/clients/traffic/{email}` (single client) |
| Client traffic | Filter by email from getClientTraffics response | `GET /panel/api/clients/traffic/{email}` — direct endpoint |

#### 2e. Reset client traffic

**File:** `app/xui_client/client.py:543-566`

| Aspect | Old | New |
|---|---|---|
| Endpoint | `POST /panel/api/inbounds/{inbound_id}/resetClientTraffic/{client_email}` | `POST /panel/api/clients/resetTraffic/{email}` |
| Identifier | inbound_id + email | Just **email** |

#### 2f. Enable/disable client

**File:** `app/xui_client/client.py:439-475`

| Aspect | Old | New |
|---|---|---|
| Method | Fetch inbound → parse settings → find client → update enable → `updateClient` | `POST /panel/api/clients/update/{email}` with `enable: true/false` |

The old approach required fetching the entire inbound settings, parsing JSON, finding the client, modifying it, and sending the whole settings back. The new API just takes the email and the fields to update.

---

### 3. Inbound response: JSON strings → nested objects

**File:** `app/xui_client/models.py:38-51`

| Aspect | Old model | New API response |
|---|---|---|
| `settings` | `str \| None` (JSON string) | **dict** (nested JSON object) |
| `stream_settings` | `str \| None` (JSON string) | **dict** (`streamSettings` — nested JSON object) |
| `sniffing` | `str \| None` (JSON string) | **dict** (nested JSON object) |

The API now returns `settings`, `streamSettings`, and `sniffing` as **parsed JSON objects**, not escaped strings. The old `XUIInbound` model defines all three as `str | None` and would fail to parse the new response.

**Fix:** Change model field types to accept both (or just dict):
```python
settings: dict | str | None = None
stream_settings: dict | str | None = None  # Note: API returns "streamSettings" (camelCase)
sniffing: dict | str | None = None
```

**Important:** The API uses camelCase `streamSettings` in the response, but the model uses snake_case `stream_settings`. Pydantic's `alias` or `model_config` is needed for field mapping.

---

### 4. New features available in v3.1.0

#### 4a. Bearer Token Authentication (no cookies needed)
- Create API tokens via `POST /panel/setting/apiTokens/create`
- Send as `Authorization: Bearer <token>` header
- Bypasses CSRF entirely, no session cookie management
- **Recommendation:** Replace cookie-based auth with Bearer tokens for programmatic access

#### 4b. CSRF Token
- `GET /csrf-token` returns a CSRF token
- Required for cookie-based `POST` requests in browser sessions
- Not needed for Bearer token auth
- **Impact:** Current code may fail on POST requests if CSRF is enforced

#### 4c. Clients API — new endpoints not previously available
- `POST /panel/api/clients/:email/attach` — attach client to additional inbounds
- `POST /panel/api/clients/:email/detach` — detach from inbounds without deleting
- `POST /panel/api/clients/bulkAdjust` — bulk shift expiry/traffic
- `GET /panel/api/clients/links/:email` — get client connection URLs
- `GET /panel/api/clients/subLinks/:subId` — get subscription links as JSON
- `POST /panel/api/clients/onlines` — currently online clients
- `POST /panel/api/clients/lastOnline` — last-seen timestamps
- `POST /panel/api/clients/ips/:email` — source IPs for a client
- `GET /panel/api/clients/list/paged` — paginated client list with filters

#### 4d. Nodes API (remote panel management)
- Full CRUD for remote 3x-ui nodes
- Health probing, latency measurement
- Metric history per node

#### 4e. Inbound improvements
- `GET /panel/api/inbounds/list/slim` — lightweight list (no full client data)
- `GET /panel/api/inbounds/options` — minimal picker for dropdowns
- `POST /panel/api/inbounds/setEnable/:id` — lightweight enable toggle

---

## Summary of affected files

| File | Required changes |
|---|---|
| `app/xui_client/client.py` | Rewrite `login()` (JSON body), rewrite all client methods to use `/panel/api/clients/` endpoints, add Bearer token auth support |
| `app/xui_client/models.py` | Update `XUIInbound` fields to accept `dict` for settings/stream_settings/sniffing, update `XUIAddClientRequest` to match new client model, add new response models |
| `app/xui_client/__init__.py` | Update exports for new models |
| `app/services/xui_service.py` | Adapt to new client methods, session management changes |
| `app/services/vpn_providers/xui_provider.py` | Adapt to new client management API |
| `app/services/sync_service.py` | Adapt to new data shapes (dict instead of JSON strings for settings) |
| `app/services/protocol_sync/xui_sync.py` | Adapt to new client data format |
| `app/database/models/services.py` | Consider adding `api_token` field to `XUIPanel` for Bearer auth |

## Migration priority

1. **Login fix** — without this, nothing works on v3.1.0
2. **Inbound model update** — settings/stream_settings/sniffing now return as dicts
3. **Client CRUD migration** — switch from inbound-embedded to `/panel/api/clients/` endpoints
4. **Bearer token auth** — replace cookie management with API tokens
5. **New features** — attach/detach, bulk adjust, links, online status, etc.
