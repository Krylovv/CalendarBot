import base64
import datetime
import hashlib
import hmac
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401

import Robokassa

CONFIG = {"merchant_login": "shop", "password1": "SECRET-PASSWORD", "is_test": True}


def decode(part):
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ConfigTest(unittest.TestCase):
    def use_config(self, content):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "robokassa.json"
        if content is not None:
            path.write_text(content)
        patcher = mock.patch.object(Robokassa, "CONFIG_PATH", str(path))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_file_means_not_configured(self):
        self.use_config(None)
        self.assertFalse(Robokassa.configured())
        with self.assertRaises(Robokassa.RobokassaError):
            Robokassa.load_config()

    def test_valid_config(self):
        self.use_config(json.dumps(CONFIG))
        self.assertTrue(Robokassa.configured())
        self.assertEqual(Robokassa.load_config(), CONFIG)

    def test_is_test_is_required(self):
        for is_test in (None, "false", 0):
            config = dict(CONFIG, is_test=is_test)
            if is_test is None:
                del config["is_test"]
            self.use_config(json.dumps(config))
            with self.assertRaisesRegex(Robokassa.RobokassaError, "is_test"):
                Robokassa.load_config()

    def test_errors_never_show_the_password(self):
        self.use_config('{"merchant_login": "shop", "password1": "SECRET-PASSWORD",')
        with self.assertRaises(Robokassa.RobokassaError) as caught:
            Robokassa.load_config()
        self.assertNotIn("SECRET", str(caught.exception))
        self.use_config(json.dumps(dict(CONFIG, merchant_login="")))
        with self.assertRaisesRegex(Robokassa.RobokassaError, "merchant_login"):
            Robokassa.load_config()


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.config = dict(CONFIG)
        load = mock.patch.object(Robokassa, "load_config", side_effect=lambda: self.config)
        load.start()
        self.addCleanup(load.stop)
        self.responses = []
        self.requests = []
        urlopen = mock.patch("urllib.request.urlopen", side_effect=self.urlopen)
        urlopen.start()
        self.addCleanup(urlopen.stop)
        inv_id = mock.patch.object(Robokassa, "last_inv_id", 0)
        inv_id.start()
        self.addCleanup(inv_id.stop)

    def urlopen(self, request, timeout):
        self.requests.append(request)
        return FakeResponse(json.dumps(self.responses.pop(0)).encode())

    def sent(self, number=0):
        # -> (method, header, payload) of a request, checking its signature
        request = self.requests[number]
        token = json.loads(request.data)
        header, body, signature = token.split(".")
        key = f"{CONFIG['merchant_login']}:{CONFIG['password1']}".encode()
        expected = hmac.new(key, f"{header}.{body}".encode(), hashlib.sha256).digest()
        self.assertEqual(base64.urlsafe_b64encode(expected).rstrip(b"=").decode(), signature)
        self.assertEqual(request.get_header("Content-type"), "application/json")
        return request.full_url.rsplit("/", 1)[1], decode(header), decode(body)

    def test_create_test_invoice(self):
        self.responses.append(
            {"isSuccess": True, "id": "abc", "invId": 5, "url": "https://pay/abc"}
        )
        invoice = Robokassa.create_invoice(
            18000,
            "Аренда зала 23.09.2026 19:30–23:30",
            now=datetime.datetime(2026, 9, 27, 12, 5, 33),
        )
        self.assertEqual(
            invoice,
            {
                "id": "abc",
                "inv_id": 123285133,
                "url": "https://pay/abc",
                "summ": 18000,
                "expires": datetime.datetime(2026, 10, 4, 12, 5),
                "test": True,
            },
        )
        method, header, payload = self.sent()
        self.assertEqual(method, "CreateInvoice")
        self.assertEqual(header, {"typ": "JWT", "alg": "HS256"})
        self.assertEqual(
            payload,
            {
                "MerchantLogin": "shop",
                "InvoiceType": "OneTime",
                "InvId": 123285133,
                "Culture": "ru",
                "OutSum": 18000,
                "Description": "Аренда зала 23.09.2026 19:30–23:30",
                "ExpirationDate": "2026-10-04T12:05:00+03:00",
                "InvoiceItems": [
                    {
                        "Name": "Аренда зала 23.09.2026 19:30–23:30",
                        "Quantity": 1,
                        "Cost": 18000,
                        "Tax": "vat5",
                        "PaymentMethod": "full_payment",
                        "PaymentObject": "service",
                    }
                ],
                "AdditionalParameters": {"IsTest": "1"},
            },
        )

    def test_inv_ids_are_nine_digit_and_never_repeat(self):
        now = datetime.datetime(2026, 9, 28, 10, 0)
        first, second = Robokassa.next_inv_id(now), Robokassa.next_inv_id(now)
        self.assertEqual(second, first + 1)
        self.assertEqual(len(str(first)), 9)
        # After a restart the clock alone keeps numbers growing
        with mock.patch.object(Robokassa, "last_inv_id", 0):
            self.assertGreater(Robokassa.next_inv_id(now + datetime.timedelta(seconds=5)), second)
        self.assertEqual(len(str(Robokassa.next_inv_id(datetime.datetime(2054, 1, 1)))), 9)
        with self.assertRaisesRegex(Robokassa.RobokassaError, "used up"):
            Robokassa.next_inv_id(datetime.datetime(2055, 1, 1))

    def test_live_invoice_has_no_test_flag(self):
        self.config["is_test"] = False
        self.responses.append({"isSuccess": True, "id": "abc", "url": "https://pay/abc"})
        self.assertFalse(Robokassa.create_invoice(100, "x")["test"])
        self.assertNotIn("AdditionalParameters", self.sent()[2])

    def test_description_is_cut(self):
        self.responses.append({"isSuccess": True, "id": "abc", "url": "https://pay/abc"})
        Robokassa.create_invoice(100, "x" * 150)
        self.assertEqual(len(self.sent()[2]["Description"]), 100)

    def test_api_error(self):
        self.responses.append({"isSuccess": False, "message": "Wrong signature"})
        with self.assertRaisesRegex(Robokassa.RobokassaError, "CreateInvoice: Wrong signature"):
            Robokassa.create_invoice(100, "x")

    def test_status_and_deactivate(self):
        self.responses += [
            {"isSuccess": True, "invoiceInformation": {"invoiceStatus": "Paid"}},
            {"isSuccess": True},
            {"isSuccess": True, "invoiceInformation": {"invoiceStatus": "Refunded"}},
        ]
        self.assertEqual(Robokassa.invoice_status("abc", True), Robokassa.PAID)
        Robokassa.deactivate("abc", True)
        with self.assertRaisesRegex(Robokassa.RobokassaError, "unknown status"):
            Robokassa.invoice_status("abc", True)
        # Without IsTest the API checks the signature against the live password
        test_ids = {"MerchantLogin": "shop", "Id": "abc", "AdditionalParameters": {"IsTest": "1"}}
        self.assertEqual(self.sent(0)[::2], ("GetInvoiceInformation", test_ids))
        self.assertEqual(self.sent(1)[::2], ("DeactivateInvoice", test_ids))

    def test_live_calls_have_no_test_flag(self):
        self.config["is_test"] = False
        self.responses.append({"isSuccess": True, "invoiceInformation": {"invoiceStatus": "Paid"}})
        Robokassa.invoice_status("abc", False)
        self.assertEqual(self.sent()[2], {"MerchantLogin": "shop", "Id": "abc"})

    def test_mode_mismatch_is_not_sent(self):
        with self.assertRaises(Robokassa.ModeMismatch):
            Robokassa.invoice_status("abc", False)
        with self.assertRaises(Robokassa.ModeMismatch):
            Robokassa.deactivate("abc", False)
        self.assertEqual(self.requests, [])

    def test_description_has_time_only(self):
        self.assertEqual(
            Robokassa.invoice_description(
                datetime.datetime(2026, 9, 23, 19, 30), datetime.datetime(2026, 9, 23, 23, 30)
            ),
            "Аренда зала 23.09.2026 19:30–23:30",
        )


if __name__ == "__main__":
    unittest.main()
