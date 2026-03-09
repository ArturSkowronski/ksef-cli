"""KSeF Dashboard TUI — Textual-based interactive interface."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Static

from . import config
from .client import KSeFClient, KSeFError


# ── Widgets ────────────────────────────────────────────────────────────


class Logo(Static):
    def render(self) -> str:
        cfg = config.load()
        nip = cfg.get("nip", "?")
        env = cfg.get("environment", "PRD")
        return (
            f"[bold #bd93f9]KSeF[/]  "
            f"[#6272a4]NIP[/] [bold]{nip}[/]  "
            f"[#6272a4]ENV[/] [bold]{env}[/]"
        )


class TabSwitch(Static):
    active = reactive("received")

    def render(self) -> str:
        r_style = "bold #f8f8f2 on #6272a4" if self.active == "received" else "#6272a4"
        i_style = "bold #f8f8f2 on #6272a4" if self.active == "issued" else "#6272a4"
        return (
            f"  [bold #bd93f9]1[/] [{r_style}]  RECEIVED  [/]"
            f"  [bold #bd93f9]2[/] [{i_style}]  ISSUED  [/]"
        )


class InfoBar(Static):
    period_label = reactive("This Month")
    date_from = reactive("")
    date_to = reactive("")
    count = reactive(0)
    is_loading = reactive(False)

    def render(self) -> str:
        if self.is_loading:
            status = "[italic #f1fa8c]loading...[/]"
        elif self.count > 0:
            status = f"[bold #50fa7b]{self.count}[/] [#6272a4]invoices[/]"
        else:
            status = "[#6272a4]no invoices[/]"
        return (
            f"  [#6272a4]Period[/]  [bold #f1fa8c]{self.period_label}[/]"
            f"  [#6272a4]([/]{self.date_from} [#6272a4]→[/] {self.date_to}[#6272a4])[/]"
            f"    {status}"
            f"    [dim #6272a4]f to change[/]"
        )


class ActionHint(Static):
    label = reactive("")

    def render(self) -> str:
        if not self.label:
            return "  [dim #6272a4]navigate with ↑ ↓[/]"
        return (
            f"  [bold #f8f8f2]{self.label}[/]"
            f"    [bold #bd93f9]enter[/] [#f8f8f2]detail[/]"
            f"  [#44475a]│[/]  [bold #bd93f9]p[/] [#f8f8f2]pdf[/]"
            f"  [#44475a]│[/]  [bold #bd93f9]d[/] [#f8f8f2]xml[/]"
        )


class Toast(Static):
    text = reactive("")

    def render(self) -> str:
        return f"  {self.text}" if self.text else ""


# ── App ────────────────────────────────────────────────────────────────


class KSeFDashboard(App):

    TITLE = "KSeF"

    CSS = """
    Screen {
        background: #282a36;
    }

    Logo {
        dock: top;
        height: 1;
        padding: 0 1;
        background: #191a21;
        color: #f8f8f2;
    }

    TabSwitch {
        dock: top;
        height: 1;
        background: #282a36;
        color: #f8f8f2;
    }

    InfoBar {
        dock: top;
        height: 1;
        background: #21222c;
        color: #f8f8f2;
    }

    #table-box {
        border-top: solid #44475a;
        border-bottom: solid #44475a;
        height: 1fr;
    }

    DataTable {
        height: 1fr;
    }

    DataTable > .datatable--header {
        background: #44475a;
        color: #f8f8f2;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #6272a4;
        color: #f8f8f2;
        text-style: bold;
    }

    DataTable > .datatable--even-row {
        background: #282a36;
    }

    DataTable > .datatable--odd-row {
        background: #21222c;
    }

    ActionHint {
        dock: bottom;
        height: 1;
        background: #191a21;
        color: #f8f8f2;
    }

    Toast {
        dock: bottom;
        height: 1;
        background: #282a36;
        color: #f8f8f2;
    }

    Footer {
        background: #191a21;
        color: #6272a4;
    }

    Footer > .footer--key {
        background: #44475a;
        color: #bd93f9;
    }

    Footer > .footer--description {
        color: #f8f8f2;
    }
    """

    BINDINGS = [
        Binding("1", "set_received", "Received", show=True),
        Binding("2", "set_issued", "Issued", show=True),
        Binding("f", "change_dates", "Period", show=True),
        Binding("p", "open_pdf", "PDF", show=True),
        Binding("d", "download_xml", "XML", show=True),
        Binding("r", "reload", "Reload", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    invoices: list[dict] = []
    received_mode: bool = True

    _PERIODS: ClassVar[list[str]] = ["This Month", "Previous Month", "This Quarter", "All"]
    _period_idx: int = 0

    def compose(self) -> ComposeResult:
        yield Logo()
        yield TabSwitch(id="tabs")
        yield InfoBar(id="info")
        with Container(id="table-box"):
            yield DataTable(id="tbl")
        yield ActionHint(id="hint")
        yield Toast(id="toast")
        yield Footer()

    def on_mount(self) -> None:
        tbl = self.query_one("#tbl", DataTable)
        tbl.cursor_type = "row"
        tbl.zebra_stripes = True
        self._setup_columns()
        self._apply_period()
        self._do_fetch()

    # ── helpers ─────────────────────────────────────────────────────────

    def _setup_columns(self) -> None:
        tbl = self.query_one("#tbl", DataTable)
        tbl.clear(columns=True)
        party = "Seller" if self.received_mode else "Buyer"
        tbl.add_columns("KSeF Number", "Invoice Nr", party, "Date", "Net", "Gross", "Cur")

    def _toast(self, msg: str) -> None:
        self.query_one("#toast", Toast).text = msg

    def _selected(self) -> dict | None:
        if not self.invoices:
            return None
        try:
            idx = self.query_one("#tbl", DataTable).cursor_row
            if 0 <= idx < len(self.invoices):
                return self.invoices[idx]
        except Exception:
            pass
        return None

    def _nr(self, inv: dict) -> str:
        return inv.get("ksefNumber", inv.get("ksefReferenceNumber", ""))

    def _period_range(self) -> list[tuple[date, date]]:
        today = date.today()
        label = self._PERIODS[self._period_idx]
        if label == "This Month":
            return [(today.replace(day=1), today)]
        elif label == "Previous Month":
            first_this = today.replace(day=1)
            last_prev = first_this - timedelta(days=1)
            return [(last_prev.replace(day=1), last_prev)]
        elif label == "This Quarter":
            q_month = ((today.month - 1) // 3) * 3 + 1
            return [(today.replace(month=q_month, day=1), today)]
        else:  # All — last 12 months in 3-month chunks (KSeF max range)
            ranges = []
            end = today
            for _ in range(4):
                start = end - timedelta(days=89)
                ranges.append((start, end))
                end = start - timedelta(days=1)
            return list(reversed(ranges))

    def _apply_period(self) -> None:
        info = self.query_one("#info", InfoBar)
        ranges = self._period_range()
        info.period_label = self._PERIODS[self._period_idx]
        info.date_from = ranges[0][0].isoformat()
        info.date_to = ranges[-1][1].isoformat()

    def _get_token(self) -> str:
        """Get session token from config. Raises if missing/expired."""
        cfg = config.load()
        token = cfg.get("session_token", "")
        if not token:
            raise KSeFError("NO_SESSION", "Not logged in. Run: ksef auth login")
        expiry = cfg.get("session_expiry", "")
        if expiry:
            try:
                exp = datetime.fromisoformat(expiry)
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) >= exp:
                    raise KSeFError("EXPIRED", "Session expired. Run: ksef auth login")
            except ValueError:
                pass
        return token

    # ── row highlight ──────────────────────────────────────────────────

    def on_data_table_row_highlighted(self, _: DataTable.RowHighlighted) -> None:
        inv = self._selected()
        hint = self.query_one("#hint", ActionHint)
        if inv:
            who = (
                (inv.get("seller") or {}).get("name", "")
                if self.received_mode
                else (inv.get("buyer") or {}).get("name", "")
            )
            gross = inv.get("grossAmount", inv.get("gross", ""))
            hint.label = f"{who}  {gross} PLN"
        else:
            hint.label = ""

    # ── tab toggle ─────────────────────────────────────────────────────

    def action_set_received(self) -> None:
        if not self.received_mode:
            self.received_mode = True
            self.query_one("#tabs", TabSwitch).active = "received"
            self._setup_columns()
            self._do_fetch()

    def action_set_issued(self) -> None:
        if self.received_mode:
            self.received_mode = False
            self.query_one("#tabs", TabSwitch).active = "issued"
            self._setup_columns()
            self._do_fetch()

    # ── period cycling ─────────────────────────────────────────────────

    def action_change_dates(self) -> None:
        self._period_idx = (self._period_idx + 1) % len(self._PERIODS)
        self._apply_period()
        self._do_fetch()

    # ── fetch ──────────────────────────────────────────────────────────

    def action_reload(self) -> None:
        self._do_fetch()

    def _set_loading(self, v: bool) -> None:
        self.query_one("#info", InfoBar).is_loading = v

    def _set_count(self, n: int) -> None:
        self.query_one("#info", InfoBar).count = n

    @work(thread=True)
    def _do_fetch(self) -> None:
        self.call_from_thread(self._set_loading, True)
        self.call_from_thread(self._toast, "")

        try:
            token = self._get_token()
        except KSeFError as e:
            self.call_from_thread(self._set_loading, False)
            self.call_from_thread(self._toast, f"[#ff5555]{e.message}[/]")
            return

        ranges = self._period_range()
        subject = "subject2" if self.received_mode else "subject1"
        all_inv: list[dict] = []

        try:
            with KSeFClient(access_token=token) as c:
                for d_from, d_to in ranges:
                    payload: dict = {
                        "subjectType": subject,
                        "dateRange": {
                            "dateType": "invoicing",
                            "from": f"{d_from.isoformat()}T00:00:00.000Z",
                            "to": f"{d_to.isoformat()}T23:59:59.999Z",
                        },
                    }
                    while True:
                        r = c.query_invoice_metadata(payload)
                        all_inv.extend(r.get("invoices", r.get("invoiceHeaderList", [])))
                        if not r.get("hasMore") or not r.get("_continuationToken"):
                            break
                        payload["continuationToken"] = r["_continuationToken"]
        except KSeFError as e:
            self.call_from_thread(self._set_loading, False)
            self.call_from_thread(self._toast, f"[#ff5555]{e.message}[/]")
            return
        except Exception as e:
            self.call_from_thread(self._set_loading, False)
            self.call_from_thread(self._toast, f"[#ff5555]{e}[/]")
            return

        self.invoices = all_inv
        self.call_from_thread(self._populate)
        self.call_from_thread(self._set_count, len(all_inv))
        self.call_from_thread(self._set_loading, False)

    def _populate(self) -> None:
        tbl = self.query_one("#tbl", DataTable)
        tbl.clear()
        for inv in self.invoices:
            nr = self._nr(inv)
            inv_nr = inv.get("invoiceNumber", inv.get("invoiceReferenceNumber", ""))
            dt = (inv.get("issueDate") or inv.get("acquisitionTimestamp", "") or "")[:10]
            party = (
                (inv.get("seller") or {}).get("name", "")
                if self.received_mode
                else (inv.get("buyer") or {}).get("name", "")
            )
            net = str(inv.get("netAmount", inv.get("net", "")))
            gross = str(inv.get("grossAmount", inv.get("gross", "")))
            cur = inv.get("currency", "PLN")
            tbl.add_row(nr, inv_nr, party, dt, net, gross, cur)

    # ── detail on enter ────────────────────────────────────────────────

    def on_data_table_row_selected(self, _: DataTable.RowSelected) -> None:
        inv = self._selected()
        if not inv:
            return
        seller = (inv.get("seller") or {}).get("name", "")
        buyer = (inv.get("buyer") or {}).get("name", "")
        self._toast(
            f"[bold #bd93f9]{self._nr(inv)}[/]  "
            f"{inv.get('invoiceNumber', '')}  "
            f"[#6272a4]│[/]  {seller} [#6272a4]→[/] {buyer}  "
            f"[#6272a4]│[/]  {inv.get('issueDate', '')}  "
            f"[#6272a4]│[/]  net [bold]{inv.get('netAmount', '')}[/]  "
            f"vat [bold]{inv.get('vatAmount', '')}[/]  "
            f"gross [bold #50fa7b]{inv.get('grossAmount', '')}[/]"
        )

    # ── download xml ───────────────────────────────────────────────────

    def action_download_xml(self) -> None:
        inv = self._selected()
        if not inv:
            self._toast("[#f1fa8c]No invoice selected[/]")
            return
        self._do_download(self._nr(inv))

    @work(thread=True)
    def _do_download(self, nr: str) -> None:
        self.call_from_thread(self._toast, "[#f1fa8c]Downloading...[/]")
        try:
            token = self._get_token()
            with KSeFClient(access_token=token) as c:
                xml = c.get_invoice_by_ksef(nr)
            out = Path(f"{nr}.xml")
            out.write_bytes(xml)
            self.call_from_thread(self._toast, f"[#50fa7b]Saved → {out}[/]")
        except KSeFError as e:
            self.call_from_thread(self._toast, f"[#ff5555]{e.message}[/]")
        except Exception as e:
            self.call_from_thread(self._toast, f"[#ff5555]{e}[/]")

    # ── open pdf ───────────────────────────────────────────────────────

    def action_open_pdf(self) -> None:
        inv = self._selected()
        if not inv:
            self._toast("[#f1fa8c]No invoice selected[/]")
            return
        self._do_pdf(self._nr(inv))

    @work(thread=True)
    def _do_pdf(self, nr: str) -> None:
        self.call_from_thread(self._toast, "[#f1fa8c]Rendering PDF...[/]")
        try:
            token = self._get_token()
            with KSeFClient(access_token=token) as c:
                xml = c.get_invoice_by_ksef(nr)
            from .pdf_renderer import render_invoice_pdf

            pdf = render_invoice_pdf(xml)
            tmp = Path(tempfile.mktemp(suffix=".pdf", prefix=f"ksef-{nr[:20]}-"))
            tmp.write_bytes(pdf)
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(tmp)])
            elif sys.platform == "win32":
                subprocess.Popen(["start", str(tmp)], shell=True)
            else:
                subprocess.Popen(["xdg-open", str(tmp)])
            self.call_from_thread(self._toast, "[#50fa7b]PDF opened[/]")
        except KSeFError as e:
            self.call_from_thread(self._toast, f"[#ff5555]{e.message}[/]")
        except Exception as e:
            self.call_from_thread(self._toast, f"[#ff5555]{e}[/]")


# ── Entry ──────────────────────────────────────────────────────────────


def run_tui() -> None:
    """Launch TUI dashboard."""
    KSeFDashboard().run()
