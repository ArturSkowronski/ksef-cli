# ksef-cli Agent Integration Design

**Date:** 2026-03-12
**Scope:** Add `--json` output flag to CLI + create agent skill

---

## Problem

ksef-cli currently outputs human-readable Rich tables and colored text. Agents (Claude Code subagents, automation scripts) cannot reliably parse this output. There is also no reference documentation in skill format for agents to load.

## Goal

1. Make ksef-cli output machine-readable with a `--json` flag
2. Provide a Claude Code skill (`skills/ksef-cli/SKILL.md`) that agents can load to use ksef-cli correctly

---

## Part 1: `--json` CLI Flag

### Commands

| Command | JSON output shape |
|---|---|
| `ksef invoice list --json` | `{"invoices": [{ksefNumber, invoiceNumber, issueDate, buyer, seller, netAmount, grossAmount, currency}]}` |
| `ksef invoice status <ref> --json` | `{"processingCode": 200, "processingDescription": "...", "ksefNumber": "..."}` |
| `ksef invoice send <file> --json` | `{"invoiceRef": "...", "ksefNumber": "...", "processingCode": 200}` |
| `ksef auth status --json` | `{"nip": "...", "environment": "PRD", "sessionActive": true, "expiresIn": 1234, "expiry": "..."}` |

### Rules

- `--json` flag on all four commands above
- When `--json`: output goes to **stdout** as valid JSON (`json.dumps(...)`), no Rich markup
- Errors always go to **stderr** as `{"error": "message"}`, exit code 1
- Without `--json`: behaviour unchanged (Rich tables, human-readable)
- `invoice generate` is excluded — its stdout is already raw XML (machine-readable by design)
- `invoice get` is excluded — its stdout is already raw XML/PDF bytes

### Implementation

Each command gains a `json_output: bool = typer.Option(False, "--json", ...)` parameter.
**The parameter must be named `json_output`, not `json`** — `json` is a stdlib module that needs to be imported.
In the `--json` branch, skip all `console.print()` calls and instead call `print(json.dumps(data))`.
Import `json` at top of each module that needs it.

When `--json` is active, XSD validation warnings are suppressed (not emitted to stderr).
When `--json` is active, errors go to **stderr** as `{"error": "message"}` with exit code 1. Without `--json`, stderr behaviour is unchanged (Rich markup).

#### `invoice send --json` with `--no-wait`

When `--no-wait`, no `ksefNumber` or `processingCode` is available at send time. Output shape:
- With `--wait` (default): `{"invoiceRef": "...", "ksefNumber": "...", "processingCode": 200}`
- With `--no-wait`: `{"invoiceRef": "...", "ksefNumber": null, "processingCode": null}`

#### `invoice status --json`

The `status` command has two paths:
- Without `--session`: calls `session_status(reference)` — returns full processing info
- With `--session <ref>`: calls `invoice_status_in_session(session_ref, reference)` — returns session-scoped status

Both paths use the same JSON output shape: `{"processingCode": int, "processingDescription": "...", "ksefNumber": "..."}`. Missing fields default to `null`.

#### `auth status --json`

`sessionActive` is `true` when: session_token is non-empty AND expiry is parseable AND expiry > now. If expiry is missing or unparseable, `sessionActive` is `false`.

`expiresIn` is in **seconds** (integer), computed as `max(0, int((expiry_dt - now).total_seconds()))`.

#### `invoice list --json`

`buyer` and `seller` fields in each invoice object are **strings** (the counterparty name extracted from `inv["buyer"]["name"]` or `inv["seller"]["name"]`), not nested objects.

---

## Part 2: Agent Skill

### Location

`skills/ksef-cli/SKILL.md` (in project root, versioned with code)

### Frontmatter

```yaml
name: ksef-cli
description: Use when an agent needs to interact with the Polish KSeF e-invoice system — list, send, download invoices or check auth session status
```

### Contents

1. **Prerequisites** — ksef installed (`pip install -e .`), `KSEF_NIP` + `KSEF_TOKEN` env vars or config set
2. **Auth check flow** — always check `ksef auth status --json` first; if `sessionActive: false`, run `ksef auth login`
3. **Each command** with exact invocation + example `--json` response
4. **Error handling** — exit code 1 means error; read stderr JSON for message
5. **Typical agent workflow** — sequence: auth check → action → parse JSON result

### Size constraint

Target: <500 words total. JSON response examples in the skill are abbreviated (key fields only); the full spec doc is the authoritative reference for exact shapes.

---

## Out of Scope

- MCP server
- `--output [json|table]` format flag (simpler `--json` suffices)
- `KSEF_OUTPUT` env var
- `invoice generate` JSON wrapping (output is XML, already machine-readable)

---

## Files to Create / Modify

| File | Change |
|---|---|
| `ksef/invoice.py` | Add `--json` to `list_invoices`, `status`, `send` |
| `ksef/auth.py` | Add `--json` to `status` |
| `skills/ksef-cli/SKILL.md` | New file |

---

## Success Criteria

- `ksef invoice list --json` outputs valid JSON parseable with `json.loads()`
- `ksef auth status --json` outputs `sessionActive` boolean
- `ksef invoice send invoice.xml --json` outputs `ksefNumber` after processing
- Agent loading the skill can correctly call all four commands without trial and error
- All existing tests pass (no behaviour change without `--json`)
