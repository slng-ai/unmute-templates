"""The billing desk's one tool: three actions over a fake ledger.

There is no ERP behind this. `_LEDGER` is three invoices held in memory and
`_CASES` is where a logged dispute goes, so the package runs on its own with
no account anywhere. Point `log_dispute` at your own system and the rest of the
package does not change: the call flow, the types and the prompts all sit above
this file.

Two jobs are real even with a fake ledger, and both are here because nothing
else in the package can do them:

  * arguments are checked by a pydantic model, so a value the model invented is
    refused with a sentence it can correct itself from rather than written into
    a case;
  * a reason is mapped to the team that owns it, which is the piece of work an
    AR team actually wants automated.

The model is a plain BaseModel: fields, Literals, lists and defaults, and no
validators. Everything it needs to say is said by the field types.
"""

import sys
import threading
import types
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError

# The compiler copies this file once per tool (`tools/<tool_name>.py`), so a
# module-level dict would give each copy its own private ledger. One module
# parked in sys.modules under a name nothing else uses is the smallest thing
# every copy can reach.
_fresh = types.ModuleType("unmute_dispute_state")
vars(_fresh).update(cases={}, lock=threading.Lock())
_state = sys.modules.setdefault("unmute_dispute_state", _fresh)

# The same zone as the `today` prefetch entry in agent.yaml, so the date this
# stamps and the date the prompt reads agree. Not the container clock, which is
# UTC: a case opened at 23:30 in Madrid would carry the following day.
_DESK_TIMEZONE = "Europe/Madrid"

_LEDGER = {
    "INV-10428": {
        "invoice_number": "INV-10428",
        "account": "Harbour Foods",
        "issued_on": "2026-08-14",
        "due_on": "2026-09-13",
        "amount": 4300.0,
        "currency": "EUR",
        "status": "overdue",
    },
    "INV-10517": {
        "invoice_number": "INV-10517",
        "account": "Harbour Foods",
        "issued_on": "2026-09-02",
        "due_on": "2026-10-02",
        "amount": 1180.5,
        "currency": "EUR",
        "status": "open",
    },
    "INV-10386": {
        "invoice_number": "INV-10386",
        "account": "Kestrel Logistics",
        "issued_on": "2026-07-28",
        "due_on": "2026-08-27",
        "amount": 960.0,
        "currency": "EUR",
        "status": "paid",
    },
}

# The write-back rule, and the reason this tool is worth having at all. A person
# reading a dispute decides this in a second and then spends ten minutes
# forwarding it; the desk decides it before the caller has hung up.
_ROUTING = {
    "pricing": "sales",
    "quantity": "logistics",
    "duplicate_invoice": "billing",
    "goods_not_received": "logistics",
    "service_quality": "sales",
    "tax_or_vat": "tax",
    "wrong_po_number": "billing",
    "other": "billing",
}


class DisputeArgs(BaseModel):
    """What the model is allowed to send, and the shape each value has to have.

    Literals do the refusing. `action` outside the three words, or `reason`
    outside the eight, never reaches the ledger, and pydantic turns "1250.00"
    into a float and "true" into a bool without anything written here.
    """

    action: Literal["look_up_invoice", "list_open_invoices", "log_dispute"]
    invoice_number: str = ""
    account: str = ""
    reason: Literal[
        "pricing",
        "quantity",
        "duplicate_invoice",
        "goods_not_received",
        "service_quality",
        "tax_or_vat",
        "wrong_po_number",
        "other",
    ] = "other"
    disputed_amount: float = 0.0
    rest_will_be_paid: bool = False
    raised_by: str = ""
    evidence: str = ""
    detail: str = ""


def _today() -> str:
    """Today in the desk's own zone, in the shape the `Date` type accepts."""
    return datetime.now(ZoneInfo(_DESK_TIMEZONE)).date().isoformat()


def _reference(invoice_number: str) -> str:
    """A case reference shaped the way the `Id` type accepts.

    Letters and digits, then any of dot, dash, underscore or colon. Short
    enough to read out loud one character at a time.
    """
    tail = "".join(c for c in invoice_number if c.isdigit())[-5:] or "00000"
    return f"DSP-{tail}-{len(_state.cases) + 1:02d}"


def dispute_desk(
    action,
    invoice_number="",
    account="",
    reason="",
    disputed_amount="",
    rest_will_be_paid="",
    raised_by="",
    evidence="",
    detail="",
):
    """Run one of the three actions and hand back what the step reads.

    Every optional argument arrives as an empty string when the model left it
    out, so the empties are dropped before the model sees them and each field's
    own default applies instead.
    """
    supplied = {
        "action": action,
        "invoice_number": invoice_number,
        "account": account,
        "reason": reason,
        "disputed_amount": disputed_amount,
        "rest_will_be_paid": rest_will_be_paid,
        "raised_by": raised_by,
        "evidence": evidence,
        "detail": detail,
    }
    try:
        args = DisputeArgs(**{k: v for k, v in supplied.items() if v != ""})
    except ValidationError as refused:
        # Back to the model as a tool result, not raised. The model gets one
        # more turn to correct itself, which is cheaper than a failed call the
        # caller hears as silence.
        return {"status": "rejected", "problem": refused.errors()[0]["msg"]}

    if args.action == "look_up_invoice":
        found = _LEDGER.get(args.invoice_number.strip().upper())
        if found is None:
            return {"status": "not_found", "problem": "no invoice with that number"}
        return {"status": "found", "invoice": dict(found)}

    if args.action == "list_open_invoices":
        wanted = args.account.strip().casefold()
        open_invoices = [
            dict(invoice)
            for invoice in _LEDGER.values()
            if invoice["status"] in ("open", "overdue")
            and (not wanted or invoice["account"].casefold() == wanted)
        ]
        return {"status": "listed", "invoices": open_invoices}

    invoice = _LEDGER.get(args.invoice_number.strip().upper())
    if invoice is None:
        return {"status": "not_found", "problem": "look the invoice up before logging a dispute"}

    case = {
        "case_id": _reference(invoice["invoice_number"]),
        "invoice_number": invoice["invoice_number"],
        "reason": args.reason,
        "disputed_amount": min(args.disputed_amount, invoice["amount"]),
        "rest_will_be_paid": args.rest_will_be_paid,
        "raised_by": args.raised_by,
        "evidence": [piece.strip() for piece in args.evidence.split(",") if piece.strip()],
        "routed_to": _ROUTING[args.reason],
        "opened_on": _today(),
    }
    with _state.lock:
        _state.cases[case["case_id"]] = dict(case, detail=args.detail)
    return {"status": "recorded", "case": case}


def _demo():
    import importlib.util
    import re

    _state.cases.clear()

    found = dispute_desk("look_up_invoice", invoice_number="inv-10428")
    assert found["status"] == "found"
    assert found["invoice"]["account"] == "Harbour Foods"
    assert dispute_desk("look_up_invoice", invoice_number="INV-99999")["status"] == "not_found"

    listed = dispute_desk("list_open_invoices", account="harbour foods")
    assert [i["invoice_number"] for i in listed["invoices"]] == ["INV-10428", "INV-10517"]

    # Everything the model sends arrives as a string on a real call. The
    # pydantic model is what turns these into a float and a bool.
    recorded = dispute_desk(
        "log_dispute",
        invoice_number="INV-10428",
        reason="duplicate_invoice",
        disputed_amount="4300",
        rest_will_be_paid="true",
        raised_by="Robin Vega",
        evidence="the earlier invoice, our remittance advice",
        detail="They say they were billed for the same delivery twice.",
    )
    assert recorded["status"] == "recorded"
    case = recorded["case"]
    assert case["disputed_amount"] == 4300.0 and case["rest_will_be_paid"] is True
    assert case["evidence"] == ["the earlier invoice", "our remittance advice"]
    assert case["routed_to"] == "billing"
    # Both of these have to satisfy their declared type, or the save that ends
    # the step is refused and the case never lands in call state.
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", case["case_id"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", case["opened_on"])

    # A dispute cannot be worth more than the invoice it is against, whatever
    # the caller heard and the model wrote down.
    over = dispute_desk(
        "log_dispute", invoice_number="INV-10517", reason="pricing", disputed_amount="99999"
    )
    assert over["case"]["disputed_amount"] == 1180.5
    assert over["case"]["routed_to"] == "sales"

    # A word outside a Literal is refused where it enters, and a dispute
    # against a number nobody looked up writes nothing.
    assert dispute_desk("log_dispute", invoice_number="INV-10428", reason="vibes")["status"] == "rejected"
    assert dispute_desk("cancel_invoice")["status"] == "rejected"
    assert dispute_desk("log_dispute", invoice_number="INV-99999")["status"] == "not_found"
    assert len(_state.cases) == 2

    # Every emitted copy of this file has to reach one store, or two tools
    # would disagree about which cases exist.
    spec = importlib.util.spec_from_file_location("dispute_copy_two", __file__)
    assert spec is not None and spec.loader is not None
    copy_two = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copy_two)
    assert copy_two._state is _state

    _state.cases.clear()
    print("dispute desk demo ok")


if __name__ == "__main__":
    _demo()
