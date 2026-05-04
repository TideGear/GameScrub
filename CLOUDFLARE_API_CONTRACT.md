# Cloudflare Worker API Contract — BannerHub Community Config System

**Analysis Date:** 2026-04-23  
**Worker Endpoint:** `https://bannerhub-configs-worker.the412banner.workers.dev`  
**GitHub Repo:** `The412Banner/bannerhub-game-configs`

---

## Endpoint Catalog

### 1. GET /list?game=<game>[&refresh=1]

**Purpose:** List all configuration files for a specific game.

**Request:**
- **Method:** GET
- **Parameters:**
  - `game` (required, string, URL-encoded): Safe game name (alphanumeric + underscore/dash only). Example: `Cyberpunk_2077`
  - `refresh` (optional, int): Set to `1` to bypass cache and fetch fresh from GitHub

**Response:** `200 OK`
```json
[
  {
    "filename": "Cyberpunk_2077-Samsung-Galaxy_S24-Adreno_750-1743712345.json",
    "sha": "<git-commit-sha>",
    "device": "Samsung Galaxy S24",
    "soc": "Adreno (TM) 750",
    "date": "2026-04-20",
    "votes": 7,
    "downloads": 42,
    "game_folder": "Cyberpunk_2077",
    "age_days": 3
  },
  ...
]
```

**Version-Agnostic Notes:**
- `soc` field is optional (present only if config file includes meta.soc)
- Backward compatibility: old configs without SOC still parse correctly
- Field order and additional fields may be added in future

**Assumptions Found:**
- Safe name format assumes alphanumeric/underscore/dash only (enforced at client upload time)
- Game folder on GitHub matches the URL-encoded game name passed to API

---

### 2. GET /download?game=<game>&file=<filename>[&sha=<commit-sha>]

**Purpose:** Retrieve the raw JSON config file content.

**Request:**
- **Method:** GET
- **Parameters:**
  - `game` (required, string, URL-encoded): Game folder name matching a folder in `configs/`
  - `file` (required, string, URL-encoded): Filename matching a JSON file in `configs/{game}/`
  - `sha` (optional, string): Git commit SHA for version pinning. If omitted, fetches latest

**Response:** `200 OK` — Raw JSON object
```json
{
  "meta": {
    "app_source": "bannerhub",
    "device": "Samsung Galaxy S24",
    "soc": "Adreno (TM) 750",
    "bh_version": "3.1.0",
    "upload_token": "a1b2c3d4e5f6g7h8",
    "settings_count": 45,
    "components_count": 2
  },
  "settings": {
    "cpu_translator": 2,
    "fps_limit": 60,
    "dxvk_async": true,
    ...
  },
  "components": [
    {
      "name": "DXVK-async-2.6",
      "url": "https://github.com/.../releases/download/.../dxvk.zip",
      "type": "DXVK"
    },
    {
      "name": "Box64-0.3.4",
      "url": "https://github.com/.../releases/download/.../box64.zip",
      "type": "Box64"
    }
  ]
}
```

**Old Format Fallback (no meta/components):**
```json
{
  "cpu_translator": 2,
  "fps_limit": 60,
  "dxvk_async": true,
  ...
}
```

**Version-Agnostic Notes:**
- Backward compatible with old flat format (no meta, no components sections)
- Future versions may add new top-level keys; clients should ignore unknown keys
- Settings values can be boolean, integer, long, or string

**Assumptions Found:**
- Client decodes base64 content (upload stores base64, download returns raw)
- Filename format: `{GameName}-{Manufacturer}-{Model}-{SOC}-{UnixTimestamp}.json`
- Settings keys follow `pc_g_setting` SharedPreferences naming convention (hardcoded in client)

---

### 3. POST /upload

**Purpose:** Upload a user's game configuration to the community database.

**Request:**
- **Method:** POST
- **Headers:** `Content-Type: application/json`
- **Body:**
```json
{
  "game": "Cyberpunk_2077",
  "filename": "Cyberpunk_2077-Samsung-Galaxy_S24-Adreno_750-1743712345.json",
  "content": "<base64-encoded-json>",
  "upload_token": "a1b2c3d4e5f6g7h8"
}
```

**Response:** `200 OK`
```json
{
  "success": true,
  "sha": "<git-commit-sha>",
  "url": "https://github.com/The412Banner/bannerhub-game-configs/blob/main/configs/Cyberpunk_2077/..."
}
```

**Error Response:** `400 Bad Request` or `500 Internal Server Error`
```json
{
  "success": false,
  "error": "Invalid game name" or "Upload failed"
}
```

**Version-Agnostic Notes:**
- Authentication is intentionally open (no app-side secret required)
- Workers validates and writes to GitHub using server-side token (Cloudflare secret)
- Abuse prevention relies on spam detection (file validation, directory checks)

**Assumptions Found:**
- `upload_token` is a random hex string generated client-side, stored in config file meta
- `content` must be base64-encoded JSON (Worker decodes before writing to GitHub)
- Game name sanitization: alphanumeric + underscore/dash, replaces other chars with underscore
- No credential checking — security relies on GitHub repo being public + file-only writes

---

### 4. POST /vote

**Purpose:** Upvote a configuration file.

**Request:**
- **Method:** POST
- **Headers:** `Content-Type: application/json`
- **Body:**
```json
{
  "sha": "<git-commit-sha>",
  "game": "Cyberpunk_2077",
  "filename": "Cyberpunk_2077-Samsung-Galaxy_S24-Adreno_750-1743712345.json"
}
```

**Response:** `200 OK`
```json
{
  "votes": 8
}
```

**Version-Agnostic Notes:**
- Stored in Cloudflare KV under key `votes:{sha}`
- Client-side deduplication: SharedPreferences `bh_config_votes` stores voted SHAs
- Worker IP-based dedup on backend (7-day TTL per IP per SHA)

**Assumptions Found:**
- Client must track vote locally to disable button after voting
- SHA is Git commit SHA from GitHub (immutable per file version)

---

### 5. POST /report

**Purpose:** Report an inappropriate or spam configuration.

**Request:**
- **Method:** POST
- **Headers:** `Content-Type: application/json`
- **Body:**
```json
{
  "sha": "<git-commit-sha>"
}
```

**Response:** `200 OK`
```json
{
  "success": true,
  "reports": 2
}
```

**Version-Agnostic Notes:**
- Stored in Cloudflare KV under key `reports:{sha}`
- Client-side deduplication: SharedPreferences `bh_config_reports` tracks reported SHAs
- Worker IP-based dedup on backend (7-day TTL per IP per SHA)

---

### 6. GET /comments?game=<game>&file=<filename>

**Purpose:** Fetch all comments for a configuration.

**Request:**
- **Method:** GET
- **Parameters:**
  - `game` (required, string, URL-encoded): Game folder name
  - `file` (required, string, URL-encoded): Config filename

**Response:** `200 OK`
```json
[
  {
    "device": "Samsung_Galaxy_S24",
    "date": "2026-04-20",
    "text": "Works great with these settings!"
  },
  {
    "device": "OnePlus_11",
    "date": "2026-04-19",
    "text": "Minor FPS drops but very stable."
  }
]
```

**Version-Agnostic Notes:**
- Stored in Cloudflare KV under key `comments:{game}/{filename}`
- Returns array (may be empty)
- Comments are immutable (no delete endpoint)

**Assumptions Found:**
- KV stores JSON array directly, max 200 comments per config
- Each comment limited to 500 characters

---

### 7. POST /comment

**Purpose:** Add a comment to a configuration.

**Request:**
- **Method:** POST
- **Headers:** `Content-Type: application/json`
- **Body:**
```json
{
  "game": "Cyberpunk_2077",
  "filename": "Cyberpunk_2077-Samsung-Galaxy_S24-Adreno_750-1743712345.json",
  "text": "Works perfectly on my device!",
  "device": "Samsung_Galaxy_S24"
}
```

**Response:** `200 OK`
```json
{
  "success": true,
  "count": 5
}
```

**Error Response:** `400 Bad Request`
```json
{
  "success": false,
  "error": "Text too long (max 500 chars)" or "Max 200 comments reached"
}
```

**Version-Agnostic Notes:**
- No authentication required
- Client automatically appends server timestamp on receipt

**Assumptions Found:**
- Device string format: `{Manufacturer}_{Model}` (underscores replace spaces)
- Text length: max 500 characters
- Comments per config: max 200 total
- Comments are stored indefinitely

---

### 8. GET /desc?sha=<commit-sha>

**Purpose:** Fetch the uploader's description for a configuration.

**Request:**
- **Method:** GET
- **Parameters:**
  - `sha` (required, string, URL-encoded): Git commit SHA

**Response:** `200 OK`
```json
{
  "text": "Optimized for Snapdragon 8 Gen 3. Balanced FPS/quality.",
  "uploaded_by": "user@example.com"
}
```

**Empty Description:** `200 OK`
```json
{
  "text": ""
}
```

**Version-Agnostic Notes:**
- Field `uploaded_by` may be absent
- Text is read-only for non-uploaders

---

### 9. POST /describe

**Purpose:** Create or update the uploader's description (token-authenticated).

**Request:**
- **Method:** POST
- **Headers:** `Content-Type: application/json`
- **Body:**
```json
{
  "sha": "<git-commit-sha>",
  "token": "<upload-token>",
  "text": "New description text (max 1000 chars)"
}
```

**Response:** `200 OK`
```json
{
  "success": true
}
```

**Error Response:** `403 Unauthorized`
```json
{
  "success": false,
  "error": "Token mismatch"
}
```

**Version-Agnostic Notes:**
- Token must match the `upload_token` embedded in the config file
- Token is the only "auth" mechanism (stored in config meta, not transmitted separately)
- Updates are idempotent

**Assumptions Found:**
- Upload token is stored verbatim in config file: `meta.upload_token`
- Worker looks up token in KV under key `token:{sha}` (set at upload time)
- Description max length: 1000 characters

---

### 10. POST /delete

**Purpose:** Delete a configuration from community (token-authenticated).

**Request:**
- **Method:** POST
- **Headers:** `Content-Type: application/json`
- **Body:**
```json
{
  "sha": "<git-commit-sha>",
  "game": "Cyberpunk_2077",
  "filename": "Cyberpunk_2077-Samsung-Galaxy_S24-Adreno_750-1743712345.json",
  "upload_token": "<upload-token>"
}
```

**Response:** `200 OK`
```json
{
  "success": true
}
```

**Error Response:** `403 Unauthorized`
```json
{
  "success": false,
  "error": "Token mismatch" or "Config not found"
}
```

**Version-Agnostic Notes:**
- Deletes file from GitHub repo
- Clears all associated KV entries (votes, reports, comments, description)
- Decrements config count for game

---

### 11. GET /games[?refresh=1]

**Purpose:** List all games with available configs.

**Request:**
- **Method:** GET
- **Parameters:**
  - `refresh` (optional, int): Set to `1` to bypass cache

**Response:** `200 OK`
```json
[
  {
    "name": "Cyberpunk_2077",
    "count": 12
  },
  {
    "name": "The_Witcher_3",
    "count": 8
  },
  ...
]
```

**Legacy Format (backward compat):**
```json
[
  "Cyberpunk_2077",
  "The_Witcher_3",
  ...
]
```

**Version-Agnostic Notes:**
- New format returns objects with `name` and `count`
- Old format returns strings (client handles both via `instanceof` check)
- Filtered: excludes `BootstrapPackagedGame` system folder from GitHub

---

## Authentication Model

**Open Upload (No App-Side Secret)**
- `/upload`: Public endpoint, no bearer token required
- Abuse prevention: GitHub repo is public, file structure limits writes to `configs/` only
- Worst case: spam uploads of junk configs (no security impact)

**Token-Authenticated Description/Delete**
- `/describe` and `/delete`: Require `upload_token` field in request body
- Token is a random hex string generated at upload time and embedded in config file
- Worker stores token in KV for comparison: `token:{sha}`
- Token is NOT sent by client in subsequent uploads (only in description/delete requests)

---

## HTTP Headers

**Request Headers (Standardized):**
- `Content-Type: application/json` (POST endpoints only)
- User-Agent: May be set by client (no validation on server)
- Connection: Keep-alive (default)

**Response Headers:**
- `Content-Type: application/json`
- `Access-Control-Allow-Origin: *` (implied, for CORS)
- Caching: Workers may cache list/games (noted in code as "cache:list:{game}", "cache:games")

---

## Version-Agnostic Contract Compliance

### ✅ Compliant (No Version Binding)

1. **Endpoint Routes & Methods** — No API version in URL path (future versions can expand endpoints without conflicts)
2. **Request Parameters** — All parameters are semantic (game name, filename); no version numbers
3. **JSON Structure** — Extensible (new fields can be added, unknown fields ignored by clients)
4. **HTTP Methods & Status Codes** — Standard REST conventions (GET, POST, 200, 400, 403)
5. **Game ID Handling** — Client determines gameId locally (from GameDetailEntity), Worker doesn't care about format
6. **Component Types** — Client passes type string freely (DXVK, VKD3D, Box64, FEXCore, GPU); Worker stores as-is

### ⚠️ HARDCODED ASSUMPTIONS FOUND

#### 1. **BannerHub Version String in Meta** (BhSettingsExporter.java:51)
```java
static final String BH_VERSION = "3.1.0";
```
**Impact:** Config files include `meta.bh_version = "3.1.0"` at export time.

**Issue:** GameHub 6.0 would need to update this constant. If 6.0 uses a different version format (e.g., "6.0.0"), configs exported from 5.x and 6.0 would be distinguishable but not incompatible.

**Recommendation:** Document that `bh_version` is optional and clients should ignore mismatches. Worker shouldn't validate/reject based on version.

---

#### 2. **SharedPreferences Key Naming Convention** (BhSettingsExporter.java:42-44)
```java
private static final String SP_PREFIX = "pc_g_setting";
private static final String SOURCES_SP = "banners_sources";
private static final String EXPORT_DIR = "BannerHub/configs";
```

**Impact:** Component keys hardcoded in `buildComponentsArray()`:
- `pc_ls_DXVK`, `pc_ls_VK3k`, `pc_set_constant_94`, `pc_set_constant_95`, `pc_ls_GPU_DRIVER_`, `pc_ls_CONTAINER_LIST`, `pc_ls_steam_client`

**Issue:** GameHub 6.0 might rename these keys. Client won't find components if SP key names change.

**Recommendation:** Make component keys configurable via Worker `/config` endpoint or document the stable key list. Alternatively, export ALL non-meta keys as generic "settings" to preserve compatibility.

---

#### 3. **Component Type Mapping** (BhSettingsExporter.java:691-700)
```java
private static int typeNameToInt(String type) {
    switch (type) {
        case "DXVK":    return 12;
        case "VKD3D":   return 13;
        case "Box64":   return 94;
        case "FEXCore": return 95;
        case "GPU":     return 10;
        default:        return 12;
    }
}
```

**Impact:** Client injects components via `ComponentInjectorHelper.injectComponent(ctx, uri, contentType)` where `contentType` is an integer constant from EmuComponents.

**Issue:** These constants are hardcoded to EmuComponents library version. GameHub 6.0 might use different integers.

**Recommendation:** Keep strings (DXVK, VKD3D, etc.) in config files. Client handles type→int mapping at apply time. Worker should never assume or validate integer type IDs.

---

#### 4. **Device Detection Method** (BhSettingsExporter.java:669-689)
```java
private static String detectSoc(Context ctx) {
    // Primary: GameHub's cached OpenGL renderer in device_info SP
    // Fallback: kernel sysfs kgsl node
    // Final fallback: Build.SOC_MODEL / HARDWARE
}
```

**Impact:** SOC string exported to config meta; used for filtering on import.

**Issue:** SOC detection logic is OS/hardware dependent. Different Android versions or future GameHub versions might use different detection methods, producing different strings for same hardware.

**Recommendation:** Treat `soc` field as informational/display only. Actual component compatibility should be determined at app install time, not from config SOC string.

---

#### 5. **Game Name Sanitization** (BhSettingsExporter.java:119-122)
```java
String safeName = gameName.replaceAll("[^a-zA-Z0-9_\\-]", "_");
```

**Impact:** Game names are normalized to alphanumeric + underscore/dash before upload.

**Issue:** If GameHub 6.0 changes game naming or allows different characters, old configs might map to wrong game folders.

**Recommendation:** Document that game names should remain URL-safe strings. Future changes should be backward compatible (e.g., map old names to new names).

---

#### 6. **File Naming Timestamp Format** (BhSettingsExporter.java:123-124)
```java
long ts = System.currentTimeMillis() / 1000;  // Unix timestamp in seconds
String fileName = safeName + "-" + manufacturer + "-" + deviceName + "-" + socModel + "-" + ts + ".json";
```

**Impact:** Filename format: `GameName-Manufacturer-Model-SOC-UnixTimestamp.json`

**Issue:** Format is hardcoded. If GameHub 6.0 wants a different format, compatibility breaks.

**Recommendation:** Keep filename format stable. Version-agnostic; client shouldn't parse filename structure (treat as opaque).

---

#### 7. **Android Build Properties** (BhSettingsExporter.java:65, 107-108, 144)
```java
String device = Build.MANUFACTURER + " " + Build.MODEL;
String soc = detectSoc(ctx);
byte[] bytes = jsonStr.getBytes("UTF-8");
String b64 = android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP);
```

**Impact:** Device identification and encoding method hardcoded.

**Issue:** If encoding changes or Android deprecates these properties, compatibility is broken.

**Recommendation:** UTF-8 encoding is stable. Build.MANUFACTURER/MODEL are stable Android APIs.

---

## API Stability Recommendations

### For GameHub 6.0 Compatibility

1. **Never reject configs with mismatched `bh_version`** — version is informational only
2. **Document the stable SP key list** — or provide a `/keys` endpoint that lists active component keys
3. **Keep component type strings stable** — don't change "DXVK", "VKD3D", etc. in config exports
4. **Game name mapping** — if game names change, implement a `/map?old_name=X` endpoint or document mapping
5. **SOC field usage** — use only for display/filtering, not for functional decisions
6. **Extend settings format gracefully** — preserve unknown keys, don't reject configs with extra fields

### For Worker API Evolution

1. **No version in URL** — add new endpoints as `/v2/list` only if breaking changes required
2. **Backward-compatible defaults** — `GET /list` should return old format if `Accept` header requests it
3. **Deprecation path** — maintain old endpoints for 6+ months after releasing new ones
4. **Client-side validation** — app version checking should happen client-side, not via API validation

---

## Summary

**The API is largely version-agnostic**, with JSON extensibility and no hardcoded version checks. However, **7 client-side assumptions** are baked into the code:

1. BH_VERSION constant (cosmetic, non-blocking)
2. SharedPreferences key naming (high risk if keys change)
3. Component type integer mapping (high risk if EmuComponents changes)
4. Device SOC detection method (medium risk, used for filtering)
5. Game name sanitization (low risk, documented format)
6. Filename timestamp format (low risk, immutable)
7. Android Build properties usage (low risk, stable APIs)

**Recommended Actions:**
- Document SP keys as stable API contract
- Provide `/config` Worker endpoint listing stable component keys
- Use string types in configs, not integers
- Treat version strings and SOC fields as metadata, not functional requirements

---

**API Version:** Stable (no explicit versioning)  
**Last Updated:** 2026-04-23  
**Cloudflare Worker Status:** Production (bannerhub-configs-worker.the412banner.workers.dev)
