# ksef-cli Agent Integration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--json` output flag to four CLI commands and create a `skills/ksef-cli/SKILL.md` agent skill.

**Architecture:** Each command gains a `json_output` Typer option that routes output to `print(json.dumps(...))` instead of Rich tables. Tests use `typer.testing.CliRunner` with mocked config and API client. The skill is a standalone markdown file.

**Tech Stack:** Python 3.11, Typer, typer.testing.CliRunner, unittest.mock, json stdlib

**Spec:** `docs/superpowers/specs/2026-03-12-agent-skill-design.md`

---

## Chunk 1: `auth status --json`

### Task 1: `ksef auth status --json`

**Files:**
- Modify: `ksef/auth.py` — add `--json` to `status` command
- Test: `tests/test_auth_cli.py` — new file

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth_cli.py`:

```python
"""CLI tests for ksef auth commands with --json flag."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from typer.testing import CliRunner

from ksef.main import app

runner = CliRunner()


def _future_expiry(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_expiry() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def test_auth_status_json_active_session():
    """--json outputs valid JSON with sessionActive=true when token is valid."""
    cfg = {
        "nip": "1234567890",
        "environment": "PRD",
        "session_token": "tok_abc123xyz",
        "session_expiry": _future_expiry(1),
        "refresh_token": "ref_abc",
        "refresh_expiry": _future_expiry(24),
    }
    with patch("ksef.auth.config.load", return_value=cfg):
        result = runner.invoke(app, ["auth", "status", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["nip"] == "1234567890"
    assert data["environment"] == "PRD"
    assert data["sessionActive"] is True
    assert data["expiresIn"] > 0
    assert "expiry" in data


def test_auth_status_json_expired_session():
    """--json outputs sessionActive=false when token is expired."""
    cfg = {
        "nip": "1234567890",
        "environment": "PRD",
        "session_token": "tok_expired",
        "session_expiry": _past_expiry(),
        "refresh_token": "",
        "refresh_expiry": "",
    }
    with patch("ksef.auth.config.load", return_value=cfg):
        result = runner.invoke(app, ["auth", "status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["sessionActive"] is False
    assert data["expiresIn"] == 0


def test_auth_status_json_no_token():
    """--json outputs sessionActive=false when no token stored."""
    cfg = {
        "nip": "1234567890",
        "environment": "PRD",
        "session_token": "",
        "session_expiry": "",
        "refresh_token": "",
        "refresh_expiry": "",
    }
    with patch("ksef.auth.config.load", return_value=cfg):
        result = runner.invoke(app, ["auth", "status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["sessionActive"] is False
    assert data["expiresIn"] == 0


def test_auth_status_no_json_unchanged():
    """Without --json, output is NOT valid JSON (Rich table, human-readable)."""
    cfg = {
        "nip": "1234567890",
        "environment": "PRD",
        "session_token": "",
        "session_expiry": "",
        "refresh_token": "",
        "refresh_expiry": "",
    }
    with patch("ksef.auth.config.load", return_value=cfg):
        result = runner.invoke(app, ["auth", "status"])

    assert result.exit_code == 0
    # Without --json the output is Rich markup, not pure JSON
    try:
        json.loads(result.output)
        assert False, "Expected non-JSON output without --json flag"
    except (json.JSONDecodeError, ValueError):
        pass  # expected
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/askowronski/Priv/ksef-cli
python -m pytest tests/test_auth_cli.py -v
```

Expected: All 4 tests FAIL (no `--json` flag on `auth status` yet).

- [ ] **Step 3: Implement `auth status --json`**

In `ksef/auth.py`, add `import json` at the top (after existing imports), then modify the `status` command:

```python
import json  # add after existing imports
```

Replace the `status` function signature and body:

```python
@app.command()
def status(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON for agent use"),
) -> None:
    """Show current session info."""
    cfg = config.load()

    nip = cfg.get("nip") or ""
    environment = cfg.get("environment", "PRD")
    session_token = cfg.get("session_token", "")
    expiry = cfg.get("session_expiry", "")
    refresh_token_val = cfg.get("refresh_token", "")

    # Compute sessionActive and expiresIn
    session_active = False
    expires_in = 0
    if session_token and expiry:
        try:
            exp_dt = datetime.fromisoformat(expiry)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if now < exp_dt:
                session_active = True
                expires_in = max(0, int((exp_dt - now).total_seconds()))
        except ValueError:
            pass

    if json_output:
        print(json.dumps({
            "nip": nip,
            "environment": environment,
            "sessionActive": session_active,
            "expiresIn": expires_in,
            "expiry": expiry or None,
        }))
        return

    # Original Rich table output (unchanged)
    table = Table(title="KSeF Session Status", show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("NIP", nip or "[dim]not set[/dim]")
    table.add_row("Environment", environment)

    if session_token:
        masked = session_token[:8] + "..." + session_token[-4:]
        table.add_row("Access Token", masked)
    else:
        table.add_row("Access Token", "[dim]none[/dim]")

    if expiry:
        try:
            exp_dt = datetime.fromisoformat(expiry)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if now < exp_dt:
                remaining = exp_dt - now
                table.add_row(
                    "Expiry",
                    f"{expiry} ([green]{int(remaining.total_seconds() // 60)} min remaining[/green])",
                )
            else:
                table.add_row("Expiry", f"{expiry} ([red]EXPIRED[/red])")
        except ValueError:
            table.add_row("Expiry", expiry)
    else:
        table.add_row("Expiry", "[dim]none[/dim]")

    if refresh_token_val:
        table.add_row("Refresh Token", refresh_token_val[:8] + "..." + refresh_token_val[-4:])
        table.add_row("Refresh Expiry", cfg.get("refresh_expiry", "[dim]unknown[/dim]"))
    else:
        table.add_row("Refresh Token", "[dim]none[/dim]")

    console.print(table)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_auth_cli.py -v
```

Expected: All 4 PASS.

- [ ] **Step 5: Run full test suite — no regressions**

```bash
python -m pytest tests/ -v
```

Expected: All existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add ksef/auth.py tests/test_auth_cli.py
git commit -m "feat: add --json flag to auth status command"
```

---

## Chunk 2: `invoice list --json`

### Task 2: `ksef invoice list --json`

**Files:**
- Modify: `ksef/invoice.py` — add `--json` to `list_invoices`
- Test: `tests/test_invoice_cli.py` — new file

- [ ] **Step 1: Write the failing tests**

Create `tests/test_invoice_cli.py`:

```python
"""CLI tests for ksef invoice commands with --json flag."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ksef.main import app

runner = CliRunner()

_FAKE_INVOICE = {
    "ksefNumber": "KSeF/100/2024",
    "invoiceNumber": "FV/1/2024",
    "issueDate": "2024-01-15",
    "buyer": {"name": "Kupujący Sp. z o.o."},
    "seller": {"name": "Sprzedający SA"},
    "netAmount": "1000.00",
    "grossAmount": "1230.00",
    "currency": "PLN",
}


def test_invoice_list_json_returns_invoices():
    """--json outputs {"invoices": [...]} with flat buyer/seller strings."""
    mock_result = {"invoices": [_FAKE_INVOICE], "hasMore": False}

    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient:
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.query_invoice_metadata.return_value = mock_result

        result = runner.invoke(app, ["invoice", "list", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "invoices" in data
    inv = data["invoices"][0]
    assert inv["ksefNumber"] == "KSeF/100/2024"
    assert inv["invoiceNumber"] == "FV/1/2024"
    assert inv["buyer"] == "Kupujący Sp. z o.o."   # flat string, not dict
    assert inv["seller"] == "Sprzedający SA"
    assert inv["netAmount"] == "1000.00"
    assert inv["currency"] == "PLN"


def test_invoice_list_json_empty():
    """--json outputs {"invoices": []} when no invoices found."""
    mock_result = {"invoices": [], "hasMore": False}

    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient:
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.query_invoice_metadata.return_value = mock_result

        result = runner.invoke(app, ["invoice", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {"invoices": []}


def test_invoice_list_no_json_unchanged():
    """Without --json, output is NOT valid JSON (Rich table)."""
    mock_result = {"invoices": [_FAKE_INVOICE], "hasMore": False}

    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient:
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.query_invoice_metadata.return_value = mock_result

        result = runner.invoke(app, ["invoice", "list"])

    assert result.exit_code == 0
    try:
        json.loads(result.output)
        assert False, "Expected non-JSON output without --json"
    except (json.JSONDecodeError, ValueError):
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_invoice_cli.py::test_invoice_list_json_returns_invoices tests/test_invoice_cli.py::test_invoice_list_json_empty tests/test_invoice_cli.py::test_invoice_list_no_json_unchanged -v
```

Expected: FAIL (no `--json` on list yet).

- [ ] **Step 3: Implement `invoice list --json`**

In `ksef/invoice.py`, add `import json` at the top. Then modify `list_invoices`:

Add parameter to signature:
```python
@app.command(name="list")
def list_invoices(
    date_from: Optional[str] = typer.Option(None, "--date-from", help="Start date YYYY-MM-DD"),
    date_to: Optional[str] = typer.Option(None, "--date-to", help="End date YYYY-MM-DD"),
    seller_nip: Optional[str] = typer.Option(None, "--seller-nip", help="Filter by seller NIP"),
    received: bool = typer.Option(False, "--received", "-r", help="List received invoices (subject2) instead of issued"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON for agent use"),
) -> None:
```

After `all_invoices` is populated (after the `while True` loop), add the JSON branch before the Rich table:

```python
    if json_output:
        result_list = []
        for inv in all_invoices:
            ksef_nr = inv.get("ksefNumber") or inv.get("ksefReferenceNumber") or ""
            inv_nr = inv.get("invoiceNumber") or inv.get("invoiceReferenceNumber") or ""
            date_val = (inv.get("issueDate") or inv.get("acquisitionTimestamp") or "")[:10]
            buyer = inv.get("buyer", {}).get("name", "") if isinstance(inv.get("buyer"), dict) else ""
            seller = inv.get("seller", {}).get("name", "") if isinstance(inv.get("seller"), dict) else ""
            net = inv.get("netAmount") or inv.get("net") or ""
            gross = inv.get("grossAmount") or inv.get("gross") or ""
            result_list.append({
                "ksefNumber": ksef_nr,
                "invoiceNumber": inv_nr,
                "issueDate": date_val,
                "buyer": buyer,
                "seller": seller,
                "netAmount": str(net),
                "grossAmount": str(gross),
                "currency": inv.get("currency", "PLN"),
            })
        print(json.dumps({"invoices": result_list}))
        return

    # IMPORTANT: this empty-list check must stay AFTER the json_output branch above,
    # so that `--json` always emits {"invoices": []} even when the list is empty.
    if not all_invoices:
        console.print("[dim]No invoices found for the given period.[/dim]")
        return
    # ... rest of Rich table code unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_invoice_cli.py::test_invoice_list_json_returns_invoices tests/test_invoice_cli.py::test_invoice_list_json_empty tests/test_invoice_cli.py::test_invoice_list_no_json_unchanged -v
```

Expected: All 3 PASS.

- [ ] **Step 5: Run full suite**

```bash
python -m pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add ksef/invoice.py tests/test_invoice_cli.py
git commit -m "feat: add --json flag to invoice list command"
```

---

## Chunk 3: `invoice status --json` and `invoice send --json`

### Task 3: `ksef invoice status --json`

**Files:**
- Modify: `ksef/invoice.py`
- Test: `tests/test_invoice_cli.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_invoice_cli.py`:

```python
def test_invoice_status_json():
    """--json outputs processingCode, ksefNumber."""
    mock_result = {
        "processingCode": 200,
        "processingDescription": "Processed successfully",
        "ksefNumber": "KSeF/200/2024",
    }
    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient:
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.session_status.return_value = mock_result

        result = runner.invoke(app, ["invoice", "status", "REF123", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["processingCode"] == 200
    assert data["ksefNumber"] == "KSeF/200/2024"
    assert data["processingDescription"] == "Processed successfully"


def test_invoice_status_json_missing_fields_are_null():
    """--json outputs null for missing optional fields."""
    mock_result = {"processingCode": 150, "processingDescription": "In progress"}
    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient:
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.session_status.return_value = mock_result

        result = runner.invoke(app, ["invoice", "status", "REF123", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["processingCode"] == 150
    assert data["ksefNumber"] is None
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_invoice_cli.py::test_invoice_status_json tests/test_invoice_cli.py::test_invoice_status_json_missing_fields_are_null -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `invoice status --json`**

Modify `status` in `ksef/invoice.py`:

```python
@app.command()
def status(
    reference: str = typer.Argument(..., help="Invoice reference number"),
    session_ref: Optional[str] = typer.Option(None, "--session", "-s", help="Session reference number"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON for agent use"),
) -> None:
    """Check the processing status of a sent invoice."""
    session_token = config.require_session()

    with KSeFClient(access_token=session_token) as client:
        try:
            if session_ref:
                result = client.invoice_status_in_session(session_ref, reference)
            else:
                result = client.session_status(reference)
        except KSeFError as exc:
            if json_output:
                import sys
                print(json.dumps({"error": str(exc)}), file=sys.stderr)
            else:
                err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

    if json_output:
        ksef_number = result.get("ksefNumber") or result.get("elementReferenceNumber") or None
        print(json.dumps({
            "processingCode": result.get("processingCode") or None,
            "processingDescription": result.get("processingDescription") or None,
            "ksefNumber": ksef_number,
        }))
        return

    # Original Rich table (unchanged)
    table = Table(title=f"Invoice Status: {reference}", show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Processing Code", str(result.get("processingCode", "")))
    table.add_row("Description", result.get("processingDescription", ""))
    ksef_number = result.get("ksefNumber", result.get("elementReferenceNumber", ""))
    if ksef_number:
        table.add_row("KSeF Number", ksef_number)
    console.print(table)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_invoice_cli.py::test_invoice_status_json tests/test_invoice_cli.py::test_invoice_status_json_missing_fields_are_null -v
```

Expected: PASS.

---

### Task 4: `ksef invoice send --json`

**Files:**
- Modify: `ksef/invoice.py`
- Test: `tests/test_invoice_cli.py`

- [ ] **Step 5: Write the failing tests** — append to `tests/test_invoice_cli.py`:

```python
def test_invoice_send_json_with_wait(tmp_path):
    """--json after send+poll outputs invoiceRef, ksefNumber, processingCode."""
    xml_file = tmp_path / "inv.xml"
    xml_file.write_bytes(b"<?xml version='1.0'?><root/>")

    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient, \
         patch("ksef.invoice._to_xml", return_value=b"<xml/>"), \
         patch("ksef.invoice.validate_xml", return_value=[]), \
         patch("ksef.invoice.generate_session_keys", return_value=(b"k" * 32, b"i" * 16)), \
         patch("ksef.invoice.encrypt_aes_key", return_value="enckey=="), \
         patch("ksef.invoice.encrypt_invoice", return_value=b"encrypted"):
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.get_public_key.return_value = [{"usage": ["SymmetricKeyEncryption"], "publicKey": "---PEM---"}]
        mock_inst.open_session.return_value = {"referenceNumber": "SESS/1"}
        mock_inst.send_invoice_in_session.return_value = {"referenceNumber": "INV/1"}
        mock_inst.close_session.return_value = {}
        mock_inst.invoice_status_in_session.return_value = {
            "processingCode": 200,
            "ksefNumber": "KSeF/999/2024",
        }

        with patch("ksef.invoice._extract_public_key", return_value="---PEM---"):
            result = runner.invoke(app, ["invoice", "send", str(xml_file), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["invoiceRef"] == "INV/1"
    assert data["ksefNumber"] == "KSeF/999/2024"
    assert data["processingCode"] == 200


def test_invoice_send_json_no_wait(tmp_path):
    """--json --no-wait outputs invoiceRef with null ksefNumber/processingCode."""
    xml_file = tmp_path / "inv.xml"
    xml_file.write_bytes(b"<?xml version='1.0'?><root/>")

    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient, \
         patch("ksef.invoice._to_xml", return_value=b"<xml/>"), \
         patch("ksef.invoice.validate_xml", return_value=[]), \
         patch("ksef.invoice.generate_session_keys", return_value=(b"k" * 32, b"i" * 16)), \
         patch("ksef.invoice.encrypt_aes_key", return_value="enckey=="), \
         patch("ksef.invoice.encrypt_invoice", return_value=b"encrypted"):
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.get_public_key.return_value = []
        mock_inst.open_session.return_value = {"referenceNumber": "SESS/1"}
        mock_inst.send_invoice_in_session.return_value = {"referenceNumber": "INV/2"}
        mock_inst.close_session.return_value = {}

        with patch("ksef.invoice._extract_public_key", return_value="---PEM---"):
            result = runner.invoke(app, ["invoice", "send", str(xml_file), "--no-wait", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["invoiceRef"] == "INV/2"
    assert data["ksefNumber"] is None
    assert data["processingCode"] is None
```

- [ ] **Step 6: Run to verify fail**

```bash
python -m pytest tests/test_invoice_cli.py::test_invoice_send_json_with_wait tests/test_invoice_cli.py::test_invoice_send_json_no_wait -v
```

Expected: FAIL.

- [ ] **Step 7: Implement `invoice send --json`**

Add `json_output: bool = typer.Option(False, "--json", help="Output as JSON for agent use")` to the `send` function signature.

Key changes in the `send` function body:
1. Suppress XSD validation warnings (`if errors:` block at line ~90) when `json_output` is True — guard with `if errors and not json_output:`
2. Suppress all `console.print(f"[dim]Session opened...")` and `console.print(f"[dim]Session closed...")` calls when `json_output` is True
3. Suppress `console.print(f"[green]Invoice sent.[/green]")` when `json_output` is True
4. After polling (or skipping poll), emit JSON:

Replace the section starting at "Step 8: Poll for status" through end of function with:

```python
        # Step 8: Poll for status + emit result
        final_ksef_number = None
        final_code = None

        if wait and invoice_ref:
            poll_result = _poll_session_status_json(client, session_ref, invoice_ref)
            if poll_result:
                final_ksef_number = poll_result.get("ksefNumber")
                final_code = poll_result.get("processingCode")

        if json_output:
            print(json.dumps({
                "invoiceRef": invoice_ref,
                "ksefNumber": final_ksef_number,
                "processingCode": final_code,
            }))
        elif wait and invoice_ref:
            # Already printed by _poll_session_status (Rich output)
            pass
```

Add a new internal helper `_poll_session_status_json` that returns the result dict instead of printing.
**Do NOT modify `_poll_session_status`** — leave it as-is to preserve the Rich error-printing behavior (`[yellow]Status check error: {exc}[/yellow]` on KSeFError).

```python
def _poll_session_status_json(client: KSeFClient, session_ref: str, invoice_ref: str) -> dict | None:
    """Poll invoice status and return the final result dict (or None on timeout/error)."""
    start = time.time()
    while time.time() - start < POLL_TIMEOUT:
        try:
            result = client.invoice_status_in_session(session_ref, invoice_ref)
        except KSeFError:
            return None
        code = result.get("processingCode", 0)
        if code == 200 or code >= 400:
            return result
        time.sleep(POLL_INTERVAL)
    return None
```

This new function is called only from the `--json` branch. The existing `_poll_session_status` (Rich output) is called only from the non-JSON branch. No duplication removal needed.

- [ ] **Step 8: Run tests**

```bash
python -m pytest tests/test_invoice_cli.py::test_invoice_send_json_with_wait tests/test_invoice_cli.py::test_invoice_send_json_no_wait -v
```

Expected: PASS.

- [ ] **Step 9: Run full suite**

```bash
python -m pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 10: Commit**

```bash
git add ksef/invoice.py tests/test_invoice_cli.py
git commit -m "feat: add --json flag to invoice status and send commands"
```

---

## Chunk 4: Agent Skill

### Task 5: Create `skills/ksef-cli/SKILL.md`

**Files:**
- Create: `skills/ksef-cli/SKILL.md`

No failing test for this task — skill correctness is validated by reading it. Use a word-count check as acceptance criteria.

- [ ] **Step 1: Create the skill directory and file**

```bash
mkdir -p /Users/askowronski/Priv/ksef-cli/skills/ksef-cli
```

Create `skills/ksef-cli/SKILL.md` with this content:

```markdown
---
name: ksef-cli
description: Use when an agent needs to interact with the Polish KSeF e-invoice system — list, send, download invoices or check auth session status via the ksef CLI tool
---

# ksef-cli

CLI tool for the Polish National e-Invoice System (KSeF). Agents use this tool to authenticate, list, send, and download invoices programmatically.

## Prerequisites

- `ksef` installed: `pip install -e .` in the project root
- Credentials configured: `KSEF_NIP` + `KSEF_TOKEN` env vars, OR run `ksef config set --nip NIP --token TOKEN`
- For PDF/image extraction: `ANTHROPIC_API_KEY` env var set

## Agent Workflow

Always check auth before any invoice operation:

```bash
ksef auth status --json
```

If `sessionActive` is `false`, log in first:

```bash
ksef auth login --nip $KSEF_NIP --token $KSEF_TOKEN
```

## Commands

### Auth Status
```bash
ksef auth status --json
# → {"nip": "1234567890", "environment": "PRD", "sessionActive": true, "expiresIn": 3542, "expiry": "2026-03-12T14:00:00+00:00"}
```

### List Invoices
```bash
ksef invoice list --json
ksef invoice list --json --date-from 2024-01-01 --date-to 2024-01-31
ksef invoice list --json --received   # received invoices instead of issued
# → {"invoices": [{"ksefNumber": "...", "invoiceNumber": "...", "issueDate": "...", "buyer": "...", "seller": "...", "netAmount": "...", "grossAmount": "...", "currency": "PLN"}]}
```

### Check Invoice Status
```bash
ksef invoice status REF_NUMBER --json
# → {"processingCode": 200, "processingDescription": "Processed", "ksefNumber": "KSeF/123/2024"}
```

### Send Invoice
```bash
ksef invoice send invoice.xml --json          # wait for processing (default)
ksef invoice send invoice.pdf --json          # auto-converts PDF to XML first
ksef invoice send invoice.xml --no-wait --json
# → {"invoiceRef": "...", "ksefNumber": "KSeF/123/2024", "processingCode": 200}
# → with --no-wait: {"invoiceRef": "...", "ksefNumber": null, "processingCode": null}
```

### Download Invoice
```bash
ksef invoice get KSeF_NUMBER --out invoice.xml    # save XML
ksef invoice get KSeF_NUMBER --pdf --out inv.pdf  # save as PDF
```

### Generate XML (no send)
```bash
ksef invoice generate invoice.pdf --out invoice.xml
```

## Error Handling

- Exit code `0` = success, exit code `1` = error
- With `--json`: errors go to **stderr** as `{"error": "message"}`
- Read stderr with: `result = subprocess.run([...], capture_output=True); err = json.loads(result.stderr)`

## Environments

Default: `PRD` (production). Switch with `ksef config set --environment TEST`.
```

- [ ] **Step 2: Verify word count**

```bash
wc -w /Users/askowronski/Priv/ksef-cli/skills/ksef-cli/SKILL.md
```

Expected: under 500 words.

- [ ] **Step 3: Commit**

```bash
git add skills/ksef-cli/SKILL.md
git commit -m "feat: add ksef-cli agent skill"
```

---

## Final Verification

- [ ] **Run full test suite one last time**

```bash
python -m pytest tests/ -v
```

Expected: All pass, no regressions.

- [ ] **Smoke test `auth status --json` parsing**

```bash
python -c "
import subprocess, json, sys
result = subprocess.run(['python', '-m', 'ksef', 'auth', 'status', '--json'],
    capture_output=True, text=True)
if result.returncode == 0:
    data = json.loads(result.stdout)
    print('OK:', data.get('sessionActive'))
else:
    print('ERROR:', result.stderr)
" 2>/dev/null || echo "(requires config — output shape test passed via unit tests)"
```
