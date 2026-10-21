# Security

## Threat model
Athena is a **single-user, local** tool. It is designed to listen on `127.0.0.1` only and to hold one person's research notes. It is not hardened for exposure to the internet or for multiple users.

Built-in measures: argon2id password hash, signed HttpOnly/SameSite=Strict session cookie, CSRF tokens on every UI write, login rate limiting, parameterised SQL, escaped templates, sanitised Markdown, a strict CSP (only same-origin scripts, no inline code), http(s)-only source URLs, and a container that runs rootless with a read-only filesystem, no capabilities and no-new-privileges.

If you expose it beyond localhost you must add TLS and an authenticating reverse proxy yourself, and set `ATHENA_COOKIE_SECURE=1`.

## Agent access (MCP)
Agents connect over MCP stdio through `podman exec -i athena python -m app.athena_mcp`. There is no token and no network listener for agents; the trust boundary is the ability to exec into your container. Connected agents can read and edit your projects, ideas, sources and notes, but the server offers **no delete tools**, supports a `--read-only` mode, validates and size-limits every input, and only accepts http(s) URLs. Content written by agents is labelled, stored as data and rendered escaped, never executed. Agents reading web pages or stored notes should treat them as untrusted (prompt injection): the server's instructions say so, but a connected agent is still only as trustworthy as the model behind it, so prefer `--read-only` for anything you do not fully trust. See [docs/mcp.md](docs/mcp.md).

## Reporting a vulnerability
Please use GitHub's private vulnerability reporting ("Security" tab → "Report a vulnerability") rather than a public issue. Expect an initial reply within a week.
