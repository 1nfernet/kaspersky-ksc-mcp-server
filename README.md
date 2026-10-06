# Kaspersky Security Center MCP Server (read-only)

An MCP server for [Kaspersky Security Center Open API](https://support.kaspersky.com/help/KSC/15.1/KSCAPI/index.html) (`KSC 15.1`).
Exposes **read-only** operations as MCP tools. No dependency on the official
`KlAkOAPI.tar.gz` — a small purpose-built client (`httpx` + `mcp` SDK) speaks
the JSON-over-HTTPS protocol directly.

## Tools (21)

All tools are annotated `readOnlyHint: true, destructiveHint: false,
idempotentHint: true, openWorldHint: true` (they call an external KSC server
over the network). Paginated tools return `{total, items|tasks, offset, limit}`.

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
| `ksc_list_tasks` | Group tasks (`ResetTasksIterator`/`GetNextTask`); reports `truncated: true` when more entries may exist than fetched |
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
fully restart Claude Desktop (tray icon → quit). Not verified here (Claude
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

Same MCP configuration as Devin CLI (shared config basis). Verify on your
machine; the Desktop docs were not reviewed in detail here.

### Devin Cloud (optional)

Web UI: **Customize → MCPs → Add custom MCP** (requires the *Manage MCP
Servers* permission), transport STDIO (command/args/env) or HTTP against a
Docker-hosted instance below. Honest caveat: a cloud session needs a network
path (VPN/Outposts) to `KSC_HOST:13299` — without it, no connection. Prefer
Devin CLI on a KSC-reachable machine.

## Connecting via Streamable HTTP

Start the server in HTTP mode (local or Docker, see below). The endpoint is:

```text
http://<host>:8000/mcp
```

### Devin Cloud (custom MCP, HTTP transport)

Per the [official Devin MCP docs](https://docs.devin.ai/work-with-devin/mcp):
**Customize → MCPs → Add custom MCP**, transport **HTTP**, Server URL
`http://<docker-host>:8000/mcp`, no authentication (the server itself has no
auth layer — the KSC credentials live as ENV inside the server process, see
the security note below). Verify with **Test tools** in the config page.

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
check with `claude mcp --help` if it errors.

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

- bind to localhost only (`127.0.0.1:8000`, the compose default) or put the
  server behind firewall/VPN;
- never expose port 8000 to the internet without a reverse proxy with auth in
  front of it;
- for Devin Cloud, reachability requires VPN/Outposts anyway (see above).

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
`docker compose up --build`.

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
