# ksef-cli: Full KSeF Client (Python) — Design Plan

**Date:** 2026-03-07
**Status:** Implemented

## Overview

`ksef-cli` is a Python CLI tool for interacting with the Polish National e-Invoice System (KSeF / Krajowy System e-Faktur). It enables authentication, FA(2) XML invoice generation from PDF/image sources, and sending/managing invoices via the KSeF production API.

## Architecture

- **Language:** Python 3.11+
- **CLI framework:** Typer (type-hint-driven, built on Click)
- **HTTP client:** httpx (sync, with single retry on network error)
- **PDF extraction:** pdfplumber (primary) + Claude API multimodal (fallback)
- **Config:** `~/.ksef/config.toml` (permissions 600), storing NIP, auth token, session token, session expiry
- **KSeF environment:** Production only (`https://ksef.mf.gov.pl`)

## Project Structure

```
ksef-cli/
├── ksef/
│   ├── __init__.py        # Version constant
│   ├── main.py            # Typer root app; registers auth, invoice, config sub-apps
│   ├── config.py          # Read/write ~/.ksef/config.toml; enforce 600 permissions
│   ├── client.py          # httpx-based KSeF API client (session management, error parsing)
│   ├── auth.py            # `ksef auth` subcommands (login, logout, status)
│   ├── invoice.py         # `ksef invoice` subcommands (send, generate, status, get, list)
│   ├── extractor.py       # PDF/image → invoice fields (pdfplumber + Claude API fallback)
│   ├── xml_builder.py     # Invoice fields dict → KSeF FA(2) XML
│   └── models.py          # Pydantic models for API responses and invoice fields
├── tests/
│   ├── test_auth.py
│   ├── test_client.py
│   ├── test_extractor.py
│   ├── test_xml_builder.py
│   └── test_invoice.py
├── docs/plans/
│   └── 2026-03-07-ksef-cli-design.md  (this file)
├── pyproject.toml
└── README.md
```

## Data Flow

### Authentication
1. `ksef auth login` → `POST /api/online/Session/AuthorisationChallenge` (NIP)
2. Sign challenge: `base64(SHA-256(challenge + "|" + token))`
3. `POST /api/online/Session/InitToken` with signed token
4. Store `sessionToken` + expiry in `~/.ksef/config.toml`

### Invoice Generate
1. Detect file type (XML → passthrough)
2. **pdfplumber**: extract text from PDF
3. Heuristic parser: extract seller/buyer NIPs, invoice number, dates, line items, totals
4. If confidence < 50% or image-only: send to **Claude API** (`claude-opus-4-6`) for multimodal extraction
5. Map to `InvoiceData` Pydantic model
6. `xml_builder.py` renders KSeF FA(2) XML

### Invoice Send
1. Run generate pipeline
2. Compute SHA-256 hash of XML
3. Base64-encode XML
4. `POST /api/online/Invoice/Send` with `SessionToken` header
5. Optionally poll `GET /api/online/Invoice/Status/{ref}` until `processingCode == 200`

## Key Design Decisions

- **Single retry on network errors** — prevents hanging on transient failures
- **Confidence threshold 50%** — below this we invoke Claude API automatically
- **Config permissions enforced** — 700 for `~/.ksef/`, 600 for `config.toml`
- **FA(2) XML namespace** — `http://crd.gov.pl/wzor/2023/06/29/12648/`
- **Claude model** — `claude-opus-4-6` for invoice extraction (multimodal)
