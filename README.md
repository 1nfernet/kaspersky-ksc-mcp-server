# Kaspersky Security Center MCP Server (read-only)

An MCP server for [Kaspersky Security Center Open API](https://support.kaspersky.com/help/KSC/15.1/KSCAPI/index.html) (`KSC 15.1`).
Exposes **read-only** operations as MCP tools. No dependency on the official
`KlAkOAPI.tar.gz` — a small purpose-built client (`httpx` + `mcp` SDK) speaks
the JSON-over-HTTPS protocol directly.

## Tools (21)

All tools are annotated `readOnlyHint: true, destructiveHint: false,
idempotentHint: true, openWorldHint: true` (they call an external KSC server
over the network). Paginated tools return `{total, items|tasks, offset, limit}`.
`ksc_list_tasks` additionally reports `truncated`: when `true`, `total` is
`null` (unknown — more entries may exist than fetched). Task listing reads
sequentially (one HTTPS call per entry, capped at 1000 scanned entries), so
prefer small `limit` values with `offset` paging over large one-shot queries.

| Tool | Description |
|---|---|
| `ksc_list_groups` | List administration groups (`HostGroup.FindGroups`), filterable, paginated |
| `ksc_get_group` | One group + direct subgroups (`GetGroupInfo`, `GetSubgroups`) |
| `ksc_find_hosts` | Search hosts by filter string, any `KLHST_*` fields (IPs, hostnames, OS, versions, status) |
| `ksc_get_host` | Host attributes (`GetHostInfo`) |
| `ksc_get_host_products` | Installed products on a host |
| `ksc_get_host_details` | Bundle: attributes + products + tags + host ID in one call |
| `ksc_get_host_tags` | Tags of a host by hostname or GUID (`HostTagsApi.GetHostTags`) |
| `ksc_list_tags` | Tag catalog (`ListTags.GetAllTags`, instance `HostsTags`) |
| `ksc_list_tasks` | Group tasks (`ResetTasksIterator`/`GetNextTask`); `truncated: true` means `total` is `null` (unknown) |
| `ksc_get_task` | Task attributes + settings + start event |
| `ksc_get_task_statistics` | Task counters per state (`GetTaskStatistics2`) |
| `ksc_get_task_host_status` | Per-host execution states, paginated (`state_mask` bitmask per docs `a00179`, `0x7F` = all states) |
| `ksc_get_task_history` | Task execution history via `EventProcessing` iterators, paginated |
| `ksc_get_tasks_of_host` | All group + global tasks of a host |
| `ksc_list_policies` | Policies of a group (`effective=true` includes inherited ones) |
| `ksc_get_policy` | Policy data (`GetPolicyData`) |
| `ksc_get_outbreak_policies` | Outbreak policies (no parameters) |
| `ksc_query_events` | Free event query with filter (`EventProcessingFactory`), paginated |
| `ksc_query_host_events` | Host-scoped event query, paginated |
| `ksc_server_status` | Server statistics bundle (`GetStaticInfo`, `GetInstanceStatistics`, `GetRunTimeInfo`) |
| `ksc_srvview_query` | Generic `SrvView` read access, e.g. `view="UmdmDevices"` |

Deliberately **not** exposed: `Policy.GetPolicyContents` returns only an
`SsContents` storage handle (no content) and would need a second read step —
`GetPolicyData` covers the read use case.

## Configuration

All secrets via environment variables (see `.env.example`). Either
user/password **or** token auth (token wins when set):

| Variable | Default | Description |
|---|---|---|
| `KSC_HOST` | — (required) | KSC server hostname or IP |
| `KSC_PORT` | `13299` | KLOAPI port |
| `KSC_USER` / `KSC_PASS` | — | Service account (read rights suffice) |
| `KSC_DOMAIN` | — | Windows domain (domain users only) |
| `KSC_INTERNAL` | `0` | `1` for internal KSC users |
| `KSC_TOKEN` | — | `KSCT` token (takes precedence over user/password) |
| `KSC_VSERVER` | — | Virtual server name (optional) |
| `KSC_VERIFY` | `false` | TLS verification: `false` for self-signed `klserver.cer`, `true`, or path to `.cer` |
| `KSC_TIMEOUT` | `30` | HTTP timeout in seconds |
| `KSC_PER_REQUEST_AUTH` | `0` | `1` = HTTP fail-closed with per-request credentials (see below) |

### Credentials per user

The server adopts `KSC_USER` / `KSC_PASS` / `KSC_TOKEN` unchanged from its own
process environment — no code change was needed for per-user credentials:

- **stdio (recommended for user separation):** whoever's MCP config starts the
  server process determines the credentials. Each person puts their **own**
  values in their **own** client config:
  - Claude Desktop: the `"env"` block in `clients/claude_desktop_config.example.json`
  - Devin CLI: `"env"` in `.devin/mcp_config.local.json` (gitignored; share only
    the server shape without secrets via `.devin/mcp_config.json`,
    see `clients/devin_mcp_stdio.example.json`)
  - Claude Code: `-e KSC_USER=… -e KSC_PASS=…` flags
- **Prefer `KSC_TOKEN` over passwords** where your KSC issues *long-lived*
  tokens (it takes precedence and keeps passwords off disk). **Do not use
  `Session.CreateToken` tokens here:** the OpenAPI docs define them as
  *one-time, 3 minutes validity* — dead after the first login/re-auth, and in
  per-request mode consumed by the very first tool call. Otherwise
  user/password.
- **No 2FA accounts:** the client implements no `KSCMFA totp=…` second step —
  use a service account without 2FA.
- **Least privilege:** everyone uses their personal KSC account with a
  read-only role. Never share admin credentials through client configs. Watch
  password expiry KSC-side for continuous operation.

### Shared HTTP operation (service account)

One container = one environment = **one service account** for all callers.
Follow Devin's recommendation for shared connections: create a dedicated
read-only KSC service account for the container. Access control for *who* may
ask lives at the MCP client; towards the KSC everything appears as the service
account.

### Per-request authentication (HTTP, `KSC_PER_REQUEST_AUTH=1`)

With the flag enabled, every HTTP request must carry its own KSC credentials —
no ENV fallback, fail-closed with a clear error otherwise (stdio always uses
ENV, as there are no headers). Two variants (verbatim wins if both are sent):

- `X-KSC-Authorization`: the KSC auth value verbatim, i.e.
  `KSCBasic user="<b64>", pass="<b64>", internal="<0|1>"` or `KSCT <token>`.
  Passed through to `Session.StartSession`, never parsed or logged.
- **Components (no Base64 by hand):** `X-KSC-User` + `X-KSC-Password`
  (plus optional `X-KSC-Domain`, `X-KSC-Internal: 1`). The server builds the
  `KSCBasic` value internally — byte-identical to what `KSC_USER`/`KSC_PASS`
  in ENV produce. Devin sends these as static `headers`, e.g.:
  `{"X-KSC-User": "api-user", "X-KSC-Password": "S3cret!"}`. Store them in
  gitignored local config; Devin's Secrets store is *not* a documented
  templating source for custom MCP headers.
- `X-KSC-VServer` (optional): Base64 virtual-server name.

Rules for components: printable ASCII only (standard HTTP clients reject
non-ASCII header values client-side) — non-ASCII credentials must be
pre-Base64-encoded via the verbatim variant. Control characters (`\r\n`,
header injection), empty values and oversized values are rejected.

Exact `KSCBasic` construction (per OpenAPI docs):

```text
KSCBasic user="<b64>", pass="<b64>", internal="<0|1>"              # internal user (no domain parameter!)
KSCBasic user="<b64>", pass="<b64>", domain="<b64>", internal="0"  # domain user
```

Rules: values are UTF-8 → Base64 in double quotes, separated by `, `, **no**
spaces around `=`. Non-ASCII names must be Base64-encoded first (after that
everything is ASCII — the server rejects anything else). Example
(`api-user` / `S3cret!`, internal):
`KSCBasic user="YXBpLXVzZXI=", pass="UzNjcmV0IQ==", internal="1"` —
byte-identical to what `KSC_USER`/`KSC_PASS`/`KSC_INTERNAL` in ENV produce.

Each tool call opens its own KSC session and closes it (`EndSession`) when
done — sessions are never shared across users. Honest limits:

- **TLS/VPN is mandatory** in this mode: passwords travel per request over
  (plain) HTTP, and this server does not terminate TLS itself — put a reverse
  proxy with TLS in front or keep it on a trusted network.
- Without a live KSC only verified up to the login attempt; end-to-end needs
  real credentials (live smoke pending).

## Installation & running (local)

Prerequisite: the KSC server (`https://KSC_HOST:13299`) must be reachable
from this machine (VPN if required). Python 3.13+.

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -e ".[dev]"
Copy-Item .env.example .env   # then fill in KSC_HOST + credentials
.\.venv\Scripts\python.exe -m ksc_mcp            # stdio (default)
.\.venv\Scripts\python.exe -m ksc_mcp --http --port 8000  # Streamable HTTP
```

## Connecting clients

### Claude Desktop

Copy `clients/claude_desktop_config.example.json` into
`%APPDATA%\Claude\claude_desktop_config.json` (merge the `mcpServers` entry
if the file exists), replacing the Python path and the `KSC_*` values. Then
fully restart Claude Desktop (tray icon → quit). Note: Claude Desktop only
supports stdio — there is no HTTP involved, so the per-user ENV model from
“Credentials per user” applies automatically. Not verified here (Claude
Desktop is not installed on this machine) — report back if the handshake fails.

### Claude Code

```powershell
claude mcp add kaspersky-ksc -- D:\path\to\.venv\Scripts\python.exe -m ksc_mcp -e KSC_HOST=ksc.example.com -e KSC_USER=api-user -e KSC_PASS=... -e KSC_VERIFY=false
```

Flag syntax not verified here (Claude Code is not installed on this machine);
check with `claude mcp --help` if it errors.

### Devin CLI

Per the [official Devin MCP docs](https://docs.devin.ai/cli/extensibility/mcp/configuration):

```powershell
devin mcp add kaspersky-ksc -- D:\path\to\.venv\Scripts\python.exe -m ksc_mcp
```

Put `KSC_*` secrets in `.devin/mcp_config.local.json` (gitignored), share the
server shape via `.devin/mcp_config.json` for the team. Run Devin CLI on a
machine that can reach the KSC server. CLI syntax not verified here (Devin
CLI is not installed on this machine).

### Devin Desktop

Same config basis as Devin CLI (`~/.config/devin/mcp_config.json` user scope
or project `.devin/mcp_config.json`, secrets in `.devin/mcp_config.local.json`).
Two ways to connect, both local (this MCP is **not** reachable from the
internet, so Devin Cloud does not apply — see below):

- **stdio:** same shape as Devin CLI above, credentials per user via `"env"`.
- **HTTP:** `url` + `transport: http` as in
  `clients/devin_mcp_http.example.json`, dedicated credentials per user via the
  `headers` field (`X-KSC-Authorization`, server with `KSC_PER_REQUEST_AUTH=1`),
  or no headers with a service-account server (flag off). Personal values stay
  in user/local scope, never in shared project configs. Desktop behavior not
  verified here (Devin Desktop is not installed on this machine).

### Devin Cloud — not applicable here

Documented for completeness only: Web UI **Customize → MCPs → Add custom MCP**
would work with transport STDIO or HTTP (see “Connecting via Streamable HTTP”
for the header variant). It does **not** apply to this deployment because the
MCP server is intranet-only — a cloud session has no network path to it (that
would require VPN/Outposts). Use Devin Desktop/CLI on a KSC-reachable machine
instead.

## Connecting via Streamable HTTP

Start the server in HTTP mode (local or Docker, see below). The endpoint is:

```text
http://<host>:8000/mcp
```

### Devin Cloud (custom MCP, HTTP transport) — not applicable here

Same reason as above (intranet-only server, no path from cloud sessions).
Kept for reference — per the [official Devin MCP docs](https://docs.devin.ai/work-with-devin/mcp):
**Customize → MCPs → Add custom MCP**, transport **HTTP**, Server URL
`http://<docker-host>:8000/mcp`. Credentials either per user via the
`headers` field (`X-KSC-Authorization`, server with `KSC_PER_REQUEST_AUTH=1`)
or via a service-account server (no headers, flag off). Verify with
**Test tools** in the config page.

### Devin CLI (HTTP)

```powershell
devin mcp add kaspersky-ksc http://<host>:8000/mcp
```

A `clients/devin_mcp_http.example.json` file shows the equivalent config-file
shape (`url` + `transport: http`). CLI syntax not verified here (Devin CLI is
not installed on this machine).

### Claude Code (HTTP)

```powershell
claude mcp add --transport http kaspersky-ksc http://<host>:8000/mcp
```

Flag syntax not verified here (Claude Code is not installed on this machine);
check with `claude mcp --help` if it errors. Per-request auth needs the
client's header option for `X-KSC-Authorization` (likewise unverified).

### MCP Inspector (HTTP)

```powershell
npx @modelcontextprotocol/inspector
```

Then connect to `http://localhost:8000/mcp` with transport
**Streamable HTTP**. Useful to click through all 21 tools without wiring up a
client first.

### Security note for HTTP mode

The HTTP server exposes **no authentication of its own** — anyone who can
reach the URL can call all 21 (read-only) tools. Therefore:

- bind to localhost only (`127.0.0.1:8000`, the compose default) or keep the
  server on a trusted network/VPN — this deployment is intranet-only by
  design, never exposed to the internet;
- if that ever changes, put a reverse proxy with TLS + auth in front of port
  8000 first (mandatory for per-request passwords, which travel per request).

## Docker

```powershell
docker build -t ksc-mcp .
docker run -p 127.0.0.1:8000:8000 --env-file .env ksc-mcp
```

The image serves Streamable HTTP on port 8000 (endpoint `/mcp`). For stdio,
override the command: `docker run -i --env-file .env ksc-mcp python -m ksc_mcp`.
`.env` is never baked into the image (see `.dockerignore`).

### Compose (recommended for HTTP mode)

```powershell
docker compose up --build -d
docker compose logs -f
docker compose down
```

`docker-compose.yml` binds port 8000 to localhost only, loads `.env` via
`env_file`, and restarts the container unless stopped. The container needs a
network route to `KSC_HOST:13299` (a remote KSC works with default bridge
networking; no `host` network required). Rebuild after code changes with
`docker compose up --build`. Pinned production dependencies live in
`requirements-lock.txt` (`pip freeze` of the tested `.venv`).

## Security model

- **Read-only by construction:** every KSC method passes an allowlist in
  `ksc_client.py` (`is_read_only_method`). All `Add/Update/Delete/Move/Run/
  Set/Import/Publish/...` counterparts raise `KscError` before any HTTP call.
  Method names are validated against `^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){1,2}$`.
- **Secrets:** only via environment variables, never in code or images.
  `mcpscan` (min-severity high) reports zero findings.
- **TLS:** default `KSC_VERIFY=false` trusts self-signed `klserver.cer` and
  logs a warning on startup. For production, point `KSC_VERIFY` at the server
  certificate or enable full verification.
- **Sessions:** authenticated sessions are cached and re-established on
  401/403; no explicit logout on shutdown (server-side expiry applies).
  Config is loaded once at startup — restart the process (or container)
  after changing ENV.
- **Logs** go to stderr only — stdout is reserved for JSON-RPC on stdio.

## Development

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q
node ..\mcp-dev-env\scripts\check-tool-annotations.mjs -- .\.venv\Scripts\python.exe -m ksc_mcp
```

Live smoke test against a real server (requires credentials):

```powershell
# after .env is filled in, e.g. via MCP Inspector pointed at stdio:
# ksc_server_status → ksc_list_groups → ksc_find_hosts(limit=5)
```
