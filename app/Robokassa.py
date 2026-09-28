import base64
import datetime
import hashlib
import hmac
import json
import os
import threading
import urllib.request

import Dates

CONFIG_PATH = "./secrets/robokassa.json"
API = "https://services.robokassa.ru/InvoiceServiceWebApi/api/"
# An unpaid invoice stops accepting payment after this; the booking can be invoiced again
INVOICE_DAYS = 7
DESCRIPTION_LIMIT = 100
ITEM_NAME_LIMIT = 128

# Receipt line of every invoice (54-FZ): without it the receipt says "free sale" or isn't made
RECEIPT_TAX = "vat5"
RECEIPT_PAYMENT_METHOD = "full_payment"
RECEIPT_PAYMENT_OBJECT = "service"

# The shop also takes payments from the Tilda site, and Robokassa sends every payment
# notification there too. Tilda's order numbers are 10-digit, so the bot keeps to 9 digits:
# a notification for a bot invoice can never match a Tilda order. Robokassa reserves a number
# only once it is paid, so it wouldn't catch the clash itself
INV_ID_BASE = 100_000_000
INV_ID_LIMIT = 1_000_000_000
INV_ID_EPOCH = datetime.datetime(2026, 1, 1)
inv_id_lock = threading.Lock()
last_inv_id = 0

NOT_PAID, PAID, EXPIRED = "NotPaid", "Paid", "Expired"
# Set by the bot itself when it deactivates an invoice; Robokassa reports these as Expired
CANCELLED = "Cancelled"


class RobokassaError(Exception):
    # Messages never contain the password, the JWT or a raw response
    pass


class ModeMismatch(RobokassaError):
    # A test invoice can be reached only with the test password, and a live one only with the live one
    pass


def configured():
    # No file, no invoice button; the rest of the bot works as before
    return os.path.exists(CONFIG_PATH)


def load_config():
    # Read on every use, so a new password needs no restart
    try:
        with open(CONFIG_PATH) as file:
            config = json.load(file)
    except (OSError, ValueError) as error:
        raise RobokassaError(f"cannot read robokassa.json: {type(error).__name__}") from None
    if not isinstance(config, dict):
        raise RobokassaError("robokassa.json must be an object")
    for key in ("merchant_login", "password1"):
        if not isinstance(config.get(key), str) or not config[key]:
            raise RobokassaError(f"robokassa.json: {key} must be a non-empty string")
    # Required on purpose: a forgotten flag must not silently switch between test and live
    if not isinstance(config.get("is_test"), bool):
        raise RobokassaError("robokassa.json: is_test must be true or false")
    return config


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt(payload, login, password):
    header = b64url(json.dumps({"typ": "JWT", "alg": "HS256"}).encode())
    body = b64url(json.dumps(payload, ensure_ascii=False).encode())
    signing_input = f"{header}.{body}".encode()
    key = f"{login}:{password}".encode()
    signature = b64url(hmac.new(key, signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{signature}"


def call(method, payload, config):
    # The body is the JWT as a JSON string; errors come as HTTP 200 with isSuccess: false.
    # In test mode every method needs IsTest (a string, as in the API docs), not only
    # CreateInvoice: without it the signature is checked against the live password
    if config["is_test"]:
        payload = dict(payload, AdditionalParameters={"IsTest": "1"})
    data = json.dumps(jwt(payload, config["merchant_login"], config["password1"])).encode()
    request = urllib.request.Request(
        API + method, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode())
    except ValueError:
        raise RobokassaError(f"{method}: response is not JSON") from None
    if not isinstance(result, dict) or not result.get("isSuccess"):
        message = result.get("message") if isinstance(result, dict) else None
        raise RobokassaError(f"{method}: {str(message or 'isSuccess is false')[:200]}")
    return result


def invoice_description(start, end):
    # Shown to the payer and printed on the receipt; time only, no personal data
    return f"Аренда зала {start:%d.%m.%Y} {start:%H:%M}–{end:%H:%M}"


def next_inv_id(now):
    # Seconds since INV_ID_EPOCH: growing across restarts, and never repeated within a run
    # (lasts until ~2054)
    global last_inv_id
    with inv_id_lock:
        inv_id = max(INV_ID_BASE + int((now - INV_ID_EPOCH).total_seconds()), last_inv_id + 1)
        if inv_id >= INV_ID_LIMIT:
            raise RobokassaError("the 9-digit InvId range is used up")
        last_inv_id = inv_id
        return inv_id


def create_invoice(summ, description, now=None):
    # -> {"id", "inv_id", "url", "summ", "expires", "test"}
    config = load_config()
    now = now or Dates.now()
    inv_id = next_inv_id(now)
    expires = now + datetime.timedelta(days=INVOICE_DAYS)
    expires = expires.replace(second=0, microsecond=0)
    payload = {
        "MerchantLogin": config["merchant_login"],
        "InvoiceType": "OneTime",
        "InvId": inv_id,
        "Culture": "ru",
        "OutSum": summ,
        "Description": description[:DESCRIPTION_LIMIT],
        "ExpirationDate": Dates.rfc3339(expires),
        "InvoiceItems": [
            {
                "Name": description[:ITEM_NAME_LIMIT],
                "Quantity": 1,
                "Cost": summ,
                "Tax": RECEIPT_TAX,
                "PaymentMethod": RECEIPT_PAYMENT_METHOD,
                "PaymentObject": RECEIPT_PAYMENT_OBJECT,
            }
        ],
    }
    result = call("CreateInvoice", payload, config)
    if not result.get("id") or not result.get("url"):
        raise RobokassaError("CreateInvoice: no id or url in the response")
    return {
        "id": str(result["id"]),
        "inv_id": inv_id,
        "url": result["url"],
        "summ": summ,
        "expires": expires,
        "test": config["is_test"],
    }


def invoice_config(test):
    config = load_config()
    if config["is_test"] != test:
        raise ModeMismatch("the invoice and robokassa.json differ in is_test")
    return config


def invoice_status(invoice_id, test):
    config = invoice_config(test)
    result = call(
        "GetInvoiceInformation",
        {"MerchantLogin": config["merchant_login"], "Id": invoice_id},
        config,
    )
    information = result.get("invoiceInformation")
    status = information.get("invoiceStatus") if isinstance(information, dict) else None
    if status not in (NOT_PAID, PAID, EXPIRED):
        raise RobokassaError(f"GetInvoiceInformation: unknown status {str(status)[:50]}")
    return status


def deactivate(invoice_id, test):
    config = invoice_config(test)
    call("DeactivateInvoice", {"MerchantLogin": config["merchant_login"], "Id": invoice_id}, config)
