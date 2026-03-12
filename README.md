# ksef-cli

> A command-line client for the Polish National e-Invoice System (KSeF). Send, receive, and manage e-invoices from your terminal — or let your AI agent do it.

Poland's KSeF system requires every invoice to be submitted as a cryptographically signed XML document through a session-encrypted API. `ksef-cli` handles all of that for you: RSA-OAEP token authentication, AES-256-CBC session encryption, FA(3) XML generation, and status polling — wrapped in a single command.

You can also hand a PDF scan to the tool and it will extract the invoice fields, build the XML, and send it — using Claude AI when the heuristic parser isn't confident enough.

---

## Installation

```bash
git clone https://github.com/ArturSkowronski/ksef-cli
cd ksef-cli
pip install -e ".[dev]"
```

Requires **Python 3.11+**.

For AI-assisted PDF extraction, set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Getting started

Save your KSeF credentials once:

```bash
ksef config set --nip 1234567890 --token <YOUR_KSEF_TOKEN>
```

Log in (this performs the full KSeF challenge/response auth and stores your session token):

```bash
ksef auth login
```

You're ready. Send your first invoice:

```bash
ksef invoice send invoice.xml
```

That's it. `ksef-cli` opens an encrypted session, uploads the invoice, closes the session, and polls until KSeF confirms processing. You get the KSeF reference number when it's done.

---

## Authentication

KSeF uses a multi-step auth flow: challenge → RSA-encrypted token → access token + refresh token. `ksef-cli` handles all of it transparently.

```bash
ksef auth login             # full auth flow, saves session
ksef auth status            # show session expiry and token info
ksef auth refresh           # refresh access token using refresh token
ksef auth logout            # clear local session tokens
```

Sessions expire in about an hour. The refresh token lasts 24 hours. Run `ksef auth refresh` to extend your session without re-entering credentials.

---

## Working with invoices

### From PDF or image to KSeF in one command

```bash
ksef invoice send invoice.pdf
```

The tool extracts invoice fields from the PDF, builds a KSeF-compliant FA(3) XML, and sends it. If the heuristic parser isn't confident (below 50%), it falls back to Claude AI multimodal analysis. You'll see a warning if confidence is low — review the generated XML before sending in that case.

### Send XML directly

```bash
ksef invoice send invoice.xml             # send and wait for processing
ksef invoice send invoice.xml --no-wait   # fire and forget
```

### Preview what will be sent

Convert to XML without sending:

```bash
ksef invoice generate invoice.pdf --out invoice.xml
ksef invoice generate invoice.pdf          # print to stdout
```

### Track and retrieve

```bash
ksef invoice status <reference>                             # check processing status
ksef invoice get <ksef-number> --out invoice.xml            # download XML
ksef invoice get <ksef-number> --pdf --out invoice.pdf      # render as PDF
```

### List invoices

```bash
ksef invoice list                                            # current month
ksef invoice list --date-from 2024-01-01 --date-to 2024-01-31
ksef invoice list --received                                 # invoices sent to you
ksef invoice list --seller-nip 9876543210                    # filter by seller
```

---

## For agents and automation

Every key command supports `--json` output. No Rich markup, no interactive prompts — just clean JSON on stdout and `{"error": "..."}` on stderr with a non-zero exit code on failure.

```bash
# Check session before doing anything
ksef auth status --json
# → {"nip": "1234567890", "environment": "PRD", "sessionActive": true, "expiresIn": 3542, "expiry": "..."}

# List invoices
ksef invoice list --json
# → {"invoices": [{"ksefNumber": "...", "invoiceNumber": "...", "buyer": "Acme Sp. z o.o.", "netAmount": "1000.00", ...}]}

# Send and get the KSeF reference back
ksef invoice send invoice.xml --json
# → {"invoiceRef": "...", "ksefNumber": "KSeF/123/2024", "processingCode": 200}

# Non-blocking send
ksef invoice send invoice.xml --no-wait --json
# → {"invoiceRef": "...", "ksefNumber": null, "processingCode": null}
```

A Claude Code agent skill is included at [`skills/ksef-cli/SKILL.md`](skills/ksef-cli/SKILL.md). Load it in any Claude Code session to give your agent the full context it needs to use `ksef-cli` correctly — auth flow, command reference, JSON shapes, and error handling patterns.

---

## Configuration

```bash
ksef config set --nip 1234567890 --token <TOKEN>
ksef config set --environment TEST    # PRD (default) | TEST | DEMO
ksef config show                      # tokens are masked
```

Config lives at `~/.ksef/config.toml` with permissions 600. Credentials never appear in logs or output.

---

## How the KSeF session flow works

KSeF v2 requires invoices to be sent inside an encrypted session:

1. Fetch the KSeF public key certificate
2. Generate a fresh AES-256 key + IV
3. Encrypt the AES key with RSA-OAEP using the KSeF public key
4. Open a session (`POST /sessions/online`) with the encrypted key
5. Encrypt the invoice XML with AES-256-CBC
6. Upload the encrypted invoice within the session
7. Close the session
8. Poll for processing status (code 200 = accepted)

`ksef-cli` runs this entire flow automatically. You just provide the XML (or the PDF).

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v          # 55 tests
```

```
ksef/
├── main.py         # CLI entry point (Typer)
├── config.py       # Config (~/.ksef/config.toml)
├── client.py       # KSeF API HTTP client (httpx)
├── auth.py         # Auth commands + RSA-OAEP encryption
├── invoice.py      # Invoice commands
├── crypto.py       # AES-256-CBC + RSA-OAEP helpers
├── extractor.py    # PDF/image → InvoiceData (pdfplumber + Claude)
├── xml_builder.py  # InvoiceData → FA(3) XML
├── models.py       # Pydantic models
├── pdf_renderer.py # XML → PDF
└── tui.py          # Interactive TUI dashboard

skills/ksef-cli/SKILL.md   # Claude Code agent skill
```

---

## License

MIT
