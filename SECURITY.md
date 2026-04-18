# Security Analysis — Portable AI Chat Server

**Threat Model:** Local-only USB device, trusted LAN, single user.  
**Not designed for:** Public internet exposure, multi-tenant use, untrusted networks.

---

## Vulnerabilities Found and Fixed

### [FIXED] Memory Exhaustion via Content-Length Spoofing
**Severity:** High  
**Description:** The server read `Content-Length` bytes from the socket unconditionally. A client sending `Content-Length: 9999999999` with a slow body could exhaust RAM.  
**Fix:** `_read_body()` enforces hard caps — 8 MB for JSON APIs, 64 MB for the Ollama proxy. Requests exceeding the limit receive HTTP 413.

---

### [FIXED] Path Traversal in Static File Serving
**Severity:** High  
**Description:** `_serve_static()` used `str.startswith()` for path containment checks. On case-insensitive filesystems or with symlinks, this could be bypassed.  
**Fix:** Uses `pathlib.Path.resolve()` + `Path.is_relative_to()` (Python 3.9+). Additionally, a whitelist of allowed extensions (`_STATIC_MIME`) blocks all non-media file types. `..` in path components is rejected before resolution.

---

### [FIXED] Ollama Proxy Path Injection
**Severity:** Medium  
**Description:** `/ollama/../some_internal_path` could reach unintended endpoints on `OLLAMA_HOST` by traversing the proxy prefix.  
**Fix:** All Ollama proxy paths are validated against a strict allowlist regex (`_OLLAMA_SAFE_PATH`) matching only known Ollama API endpoints. Non-matching paths return HTTP 403.

---

### [FIXED] Port Check Self-DoS on Restart
**Severity:** Medium (operational)  
**Description:** The preflight port check used `connect_ex()` which would detect the previous server instance as "in use" and abort startup, making the server unrestartable without manual intervention.  
**Fix:** Port check removed from preflight. `ThreadedHTTPServer` sets `allow_reuse_address = True` (SO_REUSEADDR), allowing clean rebind on the same port after restart. Preflight now checks only disk space, write permissions, and file presence.

---

### [FIXED] No JSON Schema Validation on Persisted Data
**Severity:** Medium  
**Description:** `/api/chats` and `/api/settings` accepted arbitrary JSON and wrote it to disk. A malicious POST could store gigabytes, inject unexpected keys, or corrupt the data files read by the frontend.  
**Fix:**
- `/api/chats` validates the root is a JSON array; rejects objects/primitives.
- `/api/settings` passes through `_validate_settings()` which whitelists known keys, coerces types, and caps string lengths (systemPrompt ≤ 4096 chars, temperature clamped to [0.0, 2.0]).

---

### [FIXED] Security Headers Missing
**Severity:** Low  
**Description:** No `X-Content-Type-Options` header, allowing MIME-type sniffing in older browsers.  
**Fix:** `X-Content-Type-Options: nosniff` added to all file responses.

---

## Remaining Known Limitations

### No Authentication
**Status:** By design for local USB use.  
**Risk:** Anyone on the same LAN can read/write chat history and proxy Ollama requests.  
**Mitigation:** Bind to `127.0.0.1` instead of `0.0.0.0` in `config.json` (`"network_bind": "127.0.0.1"`) if running on a shared network. A future `--auth` flag could add HTTP Basic Auth.

---

### CORS: `Access-Control-Allow-Origin: *`
**Status:** Required for local file:// access and LAN phone access.  
**Risk:** Any website the user visits can make requests to this server if the user's browser is on the same machine.  
**Mitigation:** The server only exposes non-sensitive local data. No session tokens or credentials are managed. For stricter environments, set `network_bind` to `127.0.0.1`.

---

### Prompt Injection via PDF Attachments
**Status:** Philosophical/logical risk, not a code vulnerability.  
**Description:** PDF text is injected directly into the LLM prompt. A malicious PDF could contain instructions like "Ignore all previous instructions and…" manipulating the model's behavior.  
**Mitigation:** This is a fundamental limitation of injecting untrusted text into prompts. Users should only attach PDFs they trust. A future version could add a clear delimiter and system-level instruction to treat injected content as data, not instructions.

---

### Chat History in Plaintext
**Status:** Known, optional encryption path documented.  
**Risk:** If the USB drive is lost or accessed, all conversation history is immediately readable.  
**Mitigation:** `config.json` has `"encrypt_chat_history": false` — encryption support is planned as an opt-in feature using AES-256-GCM via the `cryptography` package.

---

### `/api/stats` Exposes System Metrics
**Status:** Intentional for the UI dashboard.  
**Risk:** CPU/RAM percentages visible to anyone on the LAN — usable for fingerprinting or monitoring host activity.  
**Mitigation:** Low severity for the intended local-device threat model.

---

## Deployment Checklist

- [ ] Set `"network_bind": "127.0.0.1"` in `config.json` on shared networks
- [ ] Review `Shared/logs/` periodically and confirm no sensitive data is logged
- [ ] Do not expose port 5000 through a router's port forwarding without adding authentication
- [ ] Use the `--no-browser` flag in headless/server environments
