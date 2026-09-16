"""Accounts receivable demo tools, backed by one in-process ledger.

Four tools share this file. The compiler copies it once per tool
(`tools/<tool_name>.py`), so a module-level dict would give each tool its own
private ledger and the copies would never see each other's writes. One module
parked in `sys.modules` under a name nothing else uses is the smallest thing
every copy can reach.

Every result is a pydantic `BaseModel` returned as a dict. Plain models: fields,
literals and lists, and no validators. The rules that decide whether a promise
is legal are written out as `if` statements in the functions below, where they
read like the credit policy they are, rather than hidden in a validator that
runs on the way out.

Invoices carry an offset in days rather than a fixed due date, so the same three
accounts still have the same invoice overdue next year. One of them has nothing
overdue at all, which is the courtesy call before the due date.
"""

import sys
import threading
import types
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel

_SELLER_TIMEZONE = "Europe/London"
_MAX_PROMISE_DAYS = 60
_METHODS = ("bank_transfer", "card_link", "direct_debit")
_REASONS = (
    "pricing",
    "quantity",
    "damaged",
    "not_received",
    "duplicate",
    "already_paid",
    "other",
)

# The fictional sales ledger. Amounts are whole pounds on purpose: the voice
# says "1240 pounds" cleanly, and a demo is not the place to test how a TTS
# reads pence.
_ACCOUNTS = {
    "CU-4821": {
        "company": "Harborline Foods",
        "contact": "Dana Whitfield",
        "email": "ap@harborline.example",
    },
    "CU-5390": {
        "company": "Delta Print Works",
        "contact": "Marcus Lyle",
        "email": "accounts@deltaprint.example",
    },
    "CU-6107": {
        "company": "Calder Logistics",
        "contact": "Iris Bennett",
        "email": "payables@calder.example",
    },
}

# due_offset_days is counted from today: negative is past due, positive is not
# due yet.
_INVOICES = {
    "INV-88120": {
        "account": "CU-4821",
        "amount": 1240.0,
        "due_offset_days": -27,
        "lines": [
            {"description": "Chilled transport, week 31", "quantity": 4, "amount": 800.0},
            {"description": "Pallet hire", "quantity": 20, "amount": 440.0},
        ],
    },
    "INV-88604": {
        "account": "CU-4821",
        "amount": 980.0,
        "due_offset_days": -11,
        "lines": [
            {"description": "Chilled transport, week 33", "quantity": 4, "amount": 800.0},
            {"description": "Pallet hire", "quantity": 8, "amount": 180.0},
        ],
    },
    "INV-89011": {
        "account": "CU-4821",
        "amount": 2310.0,
        "due_offset_days": 16,
        "lines": [
            {"description": "Chilled transport, week 36", "quantity": 6, "amount": 1200.0},
            {"description": "Storage, August", "quantity": 1, "amount": 1110.0},
        ],
    },
    "INV-87744": {
        "account": "CU-5390",
        "amount": 4500.0,
        "due_offset_days": -78,
        "lines": [
            {"description": "Pallet delivery, June", "quantity": 30, "amount": 3000.0},
            {"description": "Fuel surcharge", "quantity": 1, "amount": 450.0},
            {"description": "Out of hours handling", "quantity": 6, "amount": 1050.0},
        ],
    },
    "INV-89250": {
        "account": "CU-5390",
        "amount": 615.0,
        "due_offset_days": 12,
        "lines": [
            {"description": "Print run, autumn catalogue", "quantity": 1, "amount": 615.0},
        ],
    },
    "INV-89402": {
        "account": "CU-6107",
        "amount": 3120.0,
        "due_offset_days": 9,
        "lines": [
            {"description": "Linehaul, September", "quantity": 12, "amount": 2640.0},
            {"description": "Waiting time", "quantity": 8, "amount": 480.0},
        ],
    },
}

_fresh = types.ModuleType("unmute_receivables_state")
vars(_fresh).update(
    promises={},
    disputes={},
    # ponytail: one lock for the whole ledger. Per-account locks if a real ERP
    # ever lands here and throughput matters.
    lock=threading.Lock(),
)
_state = sys.modules.setdefault("unmute_receivables_state", _fresh)


class InvoiceSummary(BaseModel):
    invoice_number: str
    amount: float
    due_date: str
    days_overdue: int
    status: Literal["due", "overdue", "on_hold"]


class InvoiceLine(BaseModel):
    description: str
    quantity: int
    amount: float


class Promise(BaseModel):
    promise_id: str
    invoice_number: str
    amount: float
    pay_date: str
    method: Literal["bank_transfer", "card_link", "direct_debit"]


class Dispute(BaseModel):
    dispute_id: str
    invoice_number: str
    reason_code: Literal[
        "pricing",
        "quantity",
        "damaged",
        "not_received",
        "duplicate",
        "already_paid",
        "other",
    ]
    detail: str
    amount_disputed: float


class Verification(BaseModel):
    account_reference: str = ""
    status: Literal["verified", "not_found", "mismatch"]
    company_name: str = ""
    contact_name: str = ""
    total_outstanding: float = 0.0
    overdue_amount: float = 0.0
    oldest_days_overdue: int = 0
    summary: str


class InvoiceResult(BaseModel):
    status: Literal["listed", "detailed", "sent", "invoice_not_found", "account_not_found"]
    summary: str
    total_outstanding: float = 0.0
    overdue_amount: float = 0.0
    sent_to: str = ""
    invoices: list[InvoiceSummary] = []
    lines: list[InvoiceLine] = []


class PromiseResult(BaseModel):
    status: Literal[
        "promised",
        "cancelled",
        "listed",
        "not_confirmed",
        "invalid_amount",
        "invalid_date",
        "invalid_method",
        "invoice_not_found",
        "invoice_disputed",
        "has_promise",
        "nothing_to_cancel",
        "account_not_found",
    ]
    summary: str
    payable_amount: float = 0.0
    promise: Promise | None = None
    promises: list[Promise] = []


class DisputeResult(BaseModel):
    status: Literal[
        "opened",
        "listed",
        "not_confirmed",
        "invalid_detail",
        "invoice_not_found",
        "already_disputed",
        "account_not_found",
    ]
    summary: str
    promise_cancelled: bool = False
    dispute: Dispute | None = None
    disputes: list[Dispute] = []


def _today() -> date:
    """The calendar date every check here runs against, in the seller's own zone.

    Not `date.today()`, which reads the container clock. That clock is UTC, so a
    call taken at 23:30 in London landed on the following day and a promise made
    for "tomorrow" was refused as being in the past. The zone matches the
    `timezone:` on the `today` prefetch entry in agent.yaml, which is what
    {{current_date}} is read in, so the prompt and the ledger agree about what
    day it is.
    """
    return datetime.now(ZoneInfo(_SELLER_TIMEZONE)).date()


def _normalize(value, prefix):
    """One reference, however it was spoken, in the shape the ledger holds it.

    A caller reads a number out and the transcript comes back as "cu 4821",
    "CU4821", "C.U. 4821" or just "4821". All four name one account, so every
    function here normalises its own argument rather than trusting the caller
    to. Bare digits get the prefix, because somebody reading off a statement
    usually says only the number. Letters with no digits, including the word
    "all", come back empty, which is how a promise against the whole account
    arrives.
    """
    kept = "".join(character for character in str(value) if character.isalnum()).upper()
    if not kept:
        return ""
    cut = next((index for index, char in enumerate(kept) if char.isdigit()), len(kept))
    letters, digits = kept[:cut] or prefix, kept[cut:]
    if not letters.isalpha() or not digits.isdigit() or not digits:
        return ""
    return letters + "-" + digits


def _money(value):
    """Pounds and pence, or -1 for anything that is not a number at all.

    -1 rather than None so the caller's own `<= 0` check catches a bad value on
    the same line it catches a zero, instead of growing a second branch.
    """
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return -1.0


def _parse_date(text):
    try:
        return date.fromisoformat(str(text).strip())
    except (TypeError, ValueError):
        return None


def _summaries(reference):
    """Every open invoice on the account, oldest first. Call under the lock."""
    held = {row["invoice_number"] for row in _state.disputes.get(reference, [])}
    today = _today()
    rows = []
    for number, invoice in _INVOICES.items():
        if invoice["account"] != reference:
            continue
        due = today + timedelta(days=invoice["due_offset_days"])
        late = max((today - due).days, 0)
        rows.append(
            InvoiceSummary(
                invoice_number=number,
                amount=invoice["amount"],
                due_date=due.isoformat(),
                days_overdue=late,
                # On hold beats overdue. It is what changes whether the invoice
                # can be chased, so it is the status worth saying out loud.
                status="on_hold" if number in held else ("overdue" if late else "due"),
            )
        )
    return sorted(rows, key=lambda row: row.due_date)


def _totals(rows):
    """Everything owed, and the part of it that is late and still chaseable."""
    total = round(sum(row.amount for row in rows), 2)
    overdue = round(sum(row.amount for row in rows if row.status == "overdue"), 2)
    return total, overdue


def verify_billing_contact(account_reference, invoice_number):
    reference = _normalize(account_reference, "CU")
    account = _ACCOUNTS.get(reference)
    if account is None:
        return Verification(
            status="not_found",
            summary="No account matches that customer number.",
        ).model_dump(exclude_none=True)

    number = _normalize(invoice_number, "INV")
    invoice = _INVOICES.get(number)
    if invoice is None or invoice["account"] != reference:
        # The reference is deliberately not returned here. An invoice number
        # that is not on the account is somebody reading from paperwork that is
        # not theirs, and nothing about the account goes back to them.
        return Verification(
            status="mismatch",
            summary="That invoice number is not on that account.",
        ).model_dump(exclude_none=True)

    with _state.lock:
        rows = _summaries(reference)
    total, overdue = _totals(rows)
    return Verification(
        account_reference=reference,
        status="verified",
        company_name=account["company"],
        contact_name=account["contact"],
        total_outstanding=total,
        overdue_amount=overdue,
        oldest_days_overdue=max((row.days_overdue for row in rows), default=0),
        summary="The billing contact was verified.",
    ).model_dump(exclude_none=True)


def manage_invoices(account_reference, action, invoice_number):
    reference = _normalize(account_reference, "CU")
    if reference not in _ACCOUNTS:
        return InvoiceResult(
            status="account_not_found",
            summary="That account is not on file.",
        ).model_dump(exclude_none=True)

    with _state.lock:
        rows = _summaries(reference)
    total, overdue = _totals(rows)

    if action == "list":
        return InvoiceResult(
            status="listed",
            summary="Nothing is open on the account." if not rows else "These invoices are open.",
            total_outstanding=total,
            overdue_amount=overdue,
            invoices=rows,
        ).model_dump(exclude_none=True)

    number = _normalize(invoice_number, "INV")
    invoice = _INVOICES.get(number)
    wrong_invoice = number and (invoice is None or invoice["account"] != reference)

    if action == "detail":
        if wrong_invoice or not number:
            return InvoiceResult(
                status="invoice_not_found",
                summary="That invoice number is not open on this account.",
                total_outstanding=total,
                overdue_amount=overdue,
                invoices=rows,
            ).model_dump(exclude_none=True)
        return InvoiceResult(
            status="detailed",
            summary="These are the lines on that invoice.",
            total_outstanding=total,
            overdue_amount=overdue,
            invoices=[row for row in rows if row.invoice_number == number],
            lines=[InvoiceLine(**line) for line in invoice["lines"]],
        ).model_dump(exclude_none=True)

    # send_copy. An empty invoice number sends the whole statement, which is
    # what "send me everything that's open" means.
    if wrong_invoice:
        return InvoiceResult(
            status="invoice_not_found",
            summary="That invoice number is not open on this account.",
            total_outstanding=total,
            overdue_amount=overdue,
            invoices=rows,
        ).model_dump(exclude_none=True)
    return InvoiceResult(
        status="sent",
        summary="A copy went to the address on file." if number else "The full statement went to the address on file.",
        total_outstanding=total,
        overdue_amount=overdue,
        sent_to=_ACCOUNTS[reference]["email"],
    ).model_dump(exclude_none=True)


def manage_promise(account_reference, action, invoice_number, amount, pay_date, method, confirmed):
    reference = _normalize(account_reference, "CU")
    if reference not in _ACCOUNTS:
        return PromiseResult(
            status="account_not_found",
            summary="That account is not on file.",
        ).model_dump(exclude_none=True)

    with _state.lock:
        rows = _summaries(reference)
        saved = _state.promises.get(reference)
    existing = [Promise(**saved)] if saved else []
    # An invoice on hold is not chaseable, so it is not part of what anybody can
    # promise to pay.
    payable = round(sum(row.amount for row in rows if row.status != "on_hold"), 2)

    if action == "list":
        return PromiseResult(
            status="listed",
            summary="There is nothing promised on the account." if not existing else "The account already has a promise to pay.",
            payable_amount=payable,
            promises=existing,
        ).model_dump(exclude_none=True)

    if confirmed is not True:
        return PromiseResult(
            status="not_confirmed",
            summary="The caller has not agreed to this yet.",
            payable_amount=payable,
        ).model_dump(exclude_none=True)

    if action == "cancel":
        if not existing:
            return PromiseResult(
                status="nothing_to_cancel",
                summary="There is no promise on the account to cancel.",
                payable_amount=payable,
            ).model_dump(exclude_none=True)
        with _state.lock:
            _state.promises.pop(reference, None)
        return PromiseResult(
            status="cancelled",
            summary="The promise was cancelled. The invoices are unchanged.",
            payable_amount=payable,
        ).model_dump(exclude_none=True)

    # One promise on an account at a time. A second one over the top of the
    # first is refused rather than stacked, and the refusal hands back what is
    # already there so the agent can say what it is.
    if existing:
        return PromiseResult(
            status="has_promise",
            summary="The account already has a promise to pay. Cancel it before making another.",
            payable_amount=payable,
            promises=existing,
        ).model_dump(exclude_none=True)

    number = _normalize(invoice_number, "INV")
    cap = payable
    if number:
        named = next((row for row in rows if row.invoice_number == number), None)
        if named is None:
            return PromiseResult(
                status="invoice_not_found",
                summary="That invoice number is not open on this account.",
                payable_amount=payable,
            ).model_dump(exclude_none=True)
        if named.status == "on_hold":
            return PromiseResult(
                status="invoice_disputed",
                summary="That invoice is on hold while a dispute is reviewed, so it is not being chased.",
                payable_amount=payable,
            ).model_dump(exclude_none=True)
        cap = named.amount

    value = _money(amount)
    if value <= 0 or value > cap:
        return PromiseResult(
            status="invalid_amount",
            summary="The amount must be more than zero and no more than what is open and not on hold.",
            payable_amount=payable,
        ).model_dump(exclude_none=True)

    when = _parse_date(pay_date)
    if when is None or when <= _today() or when > _today() + timedelta(days=_MAX_PROMISE_DAYS):
        return PromiseResult(
            status="invalid_date",
            summary="A promise has to land after today and within 60 days.",
            payable_amount=payable,
        ).model_dump(exclude_none=True)

    if method not in _METHODS:
        return PromiseResult(
            status="invalid_method",
            summary="Payment is by bank transfer, a card link, or direct debit.",
            payable_amount=payable,
        ).model_dump(exclude_none=True)

    record = Promise(
        promise_id="ptp_" + uuid4().hex[:12],
        invoice_number=number,
        amount=value,
        pay_date=when.isoformat(),
        method=method,
    )
    # setdefault rather than an assignment, so two calls landing together leave
    # one promise instead of the second quietly overwriting the first. The check
    # above gives the better message; this is the one that is actually atomic.
    with _state.lock:
        stored = _state.promises.setdefault(reference, record.model_dump())
    if stored["promise_id"] != record.promise_id:
        return PromiseResult(
            status="has_promise",
            summary="The account already has a promise to pay. Cancel it before making another.",
            payable_amount=payable,
            promises=[Promise(**stored)],
        ).model_dump(exclude_none=True)
    return PromiseResult(
        status="promised",
        summary="The promise to pay was recorded.",
        payable_amount=payable,
        promise=record,
    ).model_dump(exclude_none=True)


def manage_dispute(account_reference, action, invoice_number, reason_code, detail, amount_disputed, confirmed):
    reference = _normalize(account_reference, "CU")
    if reference not in _ACCOUNTS:
        return DisputeResult(
            status="account_not_found",
            summary="That account is not on file.",
        ).model_dump(exclude_none=True)

    with _state.lock:
        rows = _summaries(reference)
        opened = [Dispute(**row) for row in _state.disputes.get(reference, [])]

    if action == "list":
        return DisputeResult(
            status="listed",
            summary="There is nothing open on the account." if not opened else "The account has a dispute open.",
            disputes=opened,
        ).model_dump(exclude_none=True)

    if confirmed is not True:
        return DisputeResult(
            status="not_confirmed",
            summary="The caller has not agreed to the summary yet.",
        ).model_dump(exclude_none=True)

    number = _normalize(invoice_number, "INV")
    named = next((row for row in rows if row.invoice_number == number), None)
    if named is None:
        return DisputeResult(
            status="invoice_not_found",
            summary="That invoice number is not open on this account.",
        ).model_dump(exclude_none=True)

    if any(row.invoice_number == number for row in opened):
        return DisputeResult(
            status="already_disputed",
            summary="That invoice already has a dispute open on it.",
            disputes=opened,
        ).model_dump(exclude_none=True)

    clean_detail = " ".join(str(detail).split())
    if not clean_detail:
        return DisputeResult(
            status="invalid_detail",
            summary="A dispute needs one short sentence saying what is wrong.",
        ).model_dump(exclude_none=True)

    # An unknown code is recorded as other rather than refused. A code the model
    # invented is still a real dispute, and losing it to a validation error is
    # worse than filing it in the bucket a human reads anyway.
    code = reason_code if reason_code in _REASONS else "other"

    # Zero means the whole invoice, which is the common case and the one a model
    # is least likely to put a number to.
    value = _money(amount_disputed)
    if value <= 0 or value > named.amount:
        value = named.amount

    record = Dispute(
        dispute_id="dsp_" + uuid4().hex[:12],
        invoice_number=number,
        reason_code=code,
        detail=clean_detail,
        amount_disputed=value,
    )
    with _state.lock:
        _state.disputes.setdefault(reference, []).append(record.model_dump())
        saved = _state.promises.get(reference)
        # A promise against the invoice just put on hold is not a promise any
        # more. Leaving it would have the agent chasing a payment on an invoice
        # nobody is being asked to pay.
        dropped = bool(saved) and saved["invoice_number"] == number
        if dropped:
            _state.promises.pop(reference, None)
    return DisputeResult(
        status="opened",
        summary="The dispute was opened and that invoice is on hold while it is reviewed.",
        promise_cancelled=dropped,
        dispute=record,
    ).model_dump(exclude_none=True)


def _demo():
    import importlib.util
    from concurrent.futures import ThreadPoolExecutor

    assert _normalize("cu 4821", "CU") == "CU-4821"
    assert _normalize("C.U.-4821", "CU") == "CU-4821"
    assert _normalize("4821", "CU") == "CU-4821"
    assert _normalize("inv 88120", "INV") == "INV-88120"
    assert _normalize("88120", "INV") == "INV-88120"
    assert _normalize("", "INV") == ""
    assert _normalize("all", "INV") == ""

    assert verify_billing_contact("CU-9999", "INV-88120")["status"] == "not_found"
    wrong = verify_billing_contact("CU-4821", "INV-87744")
    assert wrong["status"] == "mismatch" and wrong["account_reference"] == ""
    assert not wrong["company_name"]

    verified = verify_billing_contact("cu 4821", "88120")
    assert verified["status"] == "verified"
    account = verified["account_reference"]
    assert account == "CU-4821"
    assert verified["company_name"] == "Harborline Foods"
    assert verified["contact_name"] == "Dana Whitfield"
    assert verified["total_outstanding"] == 4530.0
    assert verified["overdue_amount"] == 2220.0
    assert verified["oldest_days_overdue"] == 27

    # The courtesy call: everything open, nothing late yet.
    early = verify_billing_contact("CU-6107", "INV-89402")
    assert early["overdue_amount"] == 0.0
    assert early["oldest_days_overdue"] == 0
    assert early["total_outstanding"] == 3120.0

    # Every copy of this module shares one ledger, which is the whole point of
    # the sys.modules entry above.
    spec = importlib.util.spec_from_file_location("receivables_copy_two", __file__)
    assert spec is not None and spec.loader is not None
    copy_two = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copy_two)
    assert copy_two._state is _state

    assert manage_invoices("CU-9999", "list", "")["status"] == "account_not_found"
    listed = manage_invoices(account, "list", "")
    assert listed["status"] == "listed"
    assert [row["invoice_number"] for row in listed["invoices"]] == [
        "INV-88120",
        "INV-88604",
        "INV-89011",
    ]
    assert [row["status"] for row in listed["invoices"]] == ["overdue", "overdue", "due"]
    assert listed["invoices"][0]["due_date"] == (_today() - timedelta(days=27)).isoformat()

    assert manage_invoices(account, "detail", "INV-87744")["status"] == "invoice_not_found"
    assert manage_invoices(account, "detail", "")["status"] == "invoice_not_found"
    detailed = manage_invoices(account, "detail", "88120")
    assert detailed["status"] == "detailed"
    assert len(detailed["lines"]) == 2
    assert sum(line["amount"] for line in detailed["lines"]) == 1240.0

    sent = manage_invoices(account, "send_copy", "")
    assert sent["status"] == "sent" and sent["sent_to"] == "ap@harborline.example"
    assert manage_invoices(account, "send_copy", "INV-87744")["status"] == "invoice_not_found"

    today = _today()
    soon = (today + timedelta(days=7)).isoformat()
    far = (today + timedelta(days=90)).isoformat()

    assert manage_promise("CU-9999", "list", "", 0, "", "", False)["status"] == "account_not_found"
    empty = manage_promise(account, "list", "", 0, "", "", False)
    assert empty["status"] == "listed" and empty["promises"] == []
    assert empty["payable_amount"] == 4530.0

    assert manage_promise(account, "promise", "", 100, soon, "bank_transfer", False)["status"] == "not_confirmed"
    assert manage_promise(account, "promise", "INV-99999", 100, soon, "bank_transfer", True)["status"] == "invoice_not_found"
    assert manage_promise(account, "promise", "", 0, soon, "bank_transfer", True)["status"] == "invalid_amount"
    assert manage_promise(account, "promise", "", 9999, soon, "bank_transfer", True)["status"] == "invalid_amount"
    # A named invoice caps the promise at that invoice, not at the whole account.
    assert manage_promise(account, "promise", "INV-88604", 1500, soon, "bank_transfer", True)["status"] == "invalid_amount"
    assert manage_promise(account, "promise", "", 100, today.isoformat(), "bank_transfer", True)["status"] == "invalid_date"
    assert manage_promise(account, "promise", "", 100, "next friday", "bank_transfer", True)["status"] == "invalid_date"
    assert manage_promise(account, "promise", "", 100, far, "bank_transfer", True)["status"] == "invalid_date"
    assert manage_promise(account, "promise", "", 100, soon, "cash", True)["status"] == "invalid_method"

    promised = manage_promise(account, "promise", "88120", 1240, soon, "bank_transfer", True)
    assert promised["status"] == "promised"
    assert promised["promise"]["invoice_number"] == "INV-88120"
    assert promised["promise"]["pay_date"] == soon
    # The other copy sees it.
    assert copy_two.manage_promise(account, "list", "", 0, "", "", False)["promises"][0]["promise_id"] == promised["promise"]["promise_id"]

    blocked = manage_promise(account, "promise", "", 500, soon, "card_link", True)
    assert blocked["status"] == "has_promise"
    assert blocked["promises"][0]["promise_id"] == promised["promise"]["promise_id"]

    assert manage_dispute("CU-9999", "list", "", "", "", 0, False)["status"] == "account_not_found"
    assert manage_dispute(account, "list", "", "", "", 0, False)["disputes"] == []
    assert manage_dispute(account, "open", "INV-88120", "pricing", "Wrong rate.", 0, False)["status"] == "not_confirmed"
    assert manage_dispute(account, "open", "INV-99999", "pricing", "Wrong rate.", 0, True)["status"] == "invoice_not_found"
    assert manage_dispute(account, "open", "INV-88120", "pricing", "   ", 0, True)["status"] == "invalid_detail"

    # Opening a dispute on the promised invoice takes the promise off with it.
    opened = manage_dispute(account, "open", "88120", "pricing", "The  rate  was  agreed  lower.", 0, True)
    assert opened["status"] == "opened"
    assert opened["promise_cancelled"] is True
    assert opened["dispute"]["detail"] == "The rate was agreed lower."
    assert opened["dispute"]["amount_disputed"] == 1240.0
    assert manage_promise(account, "list", "", 0, "", "", False)["promises"] == []
    assert manage_dispute(account, "open", "88120", "pricing", "Again.", 0, True)["status"] == "already_disputed"

    # The held invoice drops out of what can be promised, and cannot be named.
    held = manage_invoices(account, "list", "")
    assert [row["status"] for row in held["invoices"]] == ["on_hold", "overdue", "due"]
    assert manage_promise(account, "promise", "INV-88120", 100, soon, "card_link", True)["status"] == "invoice_disputed"
    assert manage_promise(account, "list", "", 0, "", "", False)["payable_amount"] == 3290.0
    # A dispute is a record, not a credit note.
    assert held["total_outstanding"] == 4530.0

    # An invented reason code is filed rather than lost.
    other = verify_billing_contact("CU-5390", "INV-87744")["account_reference"]
    odd = manage_dispute(other, "open", "INV-87744", "vibes", "The fuel surcharge was never agreed.", 450, True)
    assert odd["dispute"]["reason_code"] == "other"
    assert odd["dispute"]["amount_disputed"] == 450.0
    assert odd["promise_cancelled"] is False

    assert manage_promise(other, "promise", "", 615, soon, "direct_debit", True)["status"] == "promised"
    assert manage_promise(other, "cancel", "", 0, "", "", False)["status"] == "not_confirmed"
    assert manage_promise(other, "cancel", "", 0, "", "", True)["status"] == "cancelled"
    assert manage_promise(other, "cancel", "", 0, "", "", True)["status"] == "nothing_to_cancel"

    # Two threads promising at once must leave exactly one promise.
    third = verify_billing_contact("CU-6107", "INV-89402")["account_reference"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: manage_promise(third, "promise", "", 100, soon, "bank_transfer", True),
                range(8),
            )
        )
    assert sum(row["status"] == "promised" for row in results) == 1
    assert len(manage_promise(third, "list", "", 0, "", "", False)["promises"]) == 1

    print("receivables in-memory check passed")


if __name__ == "__main__":
    _demo()
