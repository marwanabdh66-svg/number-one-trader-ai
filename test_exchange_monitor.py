import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from exchange_monitor import BinanceReadOnlyMonitor, ExchangeMonitorError


class BinanceReadOnlyMonitorTests(unittest.TestCase):
    @patch("exchange_monitor.requests.Session.get")
    def test_ping_uses_get_without_credentials(self, get):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {}
        response.raise_for_status.return_value = None
        get.return_value = response

        monitor = BinanceReadOnlyMonitor(api_key="", api_secret="")
        self.assertTrue(monitor.ping())
        self.assertEqual(get.call_args.kwargs["timeout"], 10.0)
        self.assertTrue(get.call_args.args[0].endswith("/api/v3/ping"))

    @patch("exchange_monitor.requests.Session.get")
    def test_account_is_read_only_get_and_returns_nonzero_balances(self, get):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "canTrade": False,
            "canWithdraw": False,
            "canDeposit": False,
            "accountType": "SPOT",
            "permissions": ["USER_DATA"],
            "balances": [
                {"asset": "USDT", "free": "12.5", "locked": "1.5"},
                {"asset": "BTC", "free": "0", "locked": "0"},
            ],
            "updateTime": 123,
        }
        response.raise_for_status.return_value = None
        get.return_value = response

        monitor = BinanceReadOnlyMonitor(api_key="demo-key", api_secret="demo-secret")
        account = monitor.account()

        self.assertEqual(get.call_args.kwargs["params"].get("timestamp") is not None, True)
        self.assertEqual(account["balances"], [
            {"asset": "USDT", "free": 12.5, "locked": 1.5, "total": 14.0}
        ])
        self.assertFalse(account["can_withdraw"])
        self.assertEqual(get.call_args.kwargs["headers"] if "headers" in get.call_args.kwargs else {}, {})

    @patch("exchange_monitor.requests.Session.get")
    def test_invalid_symbol_is_rejected_before_request(self, get):
        monitor = BinanceReadOnlyMonitor(api_key="demo-key", api_secret="demo-secret")
        with self.assertRaises(ExchangeMonitorError):
            monitor.open_orders("BTC/USDT")
        get.assert_not_called()

    @patch("exchange_monitor.requests.Session.get")
    def test_open_orders_uses_get_only(self, get):
        response = Mock()
        response.status_code = 200
        response.json.return_value = []
        response.raise_for_status.return_value = None
        get.return_value = response

        monitor = BinanceReadOnlyMonitor(api_key="demo-key", api_secret="demo-secret")
        self.assertEqual(monitor.open_orders("BTCUSDT"), [])
        self.assertEqual(get.call_args.kwargs["params"]["symbol"], "BTCUSDT")

    @patch("exchange_monitor.requests.Session.get")
    def test_exchange_error_does_not_expose_request_details(self, get):
        response = Mock()
        response.status_code = 403
        response.raise_for_status.side_effect = __import__("requests").HTTPError(
            "https://api.binance.com/private?signature=secret-value"
        )
        get.return_value = response

        monitor = BinanceReadOnlyMonitor(api_key="demo-key", api_secret="demo-secret")
        with self.assertRaises(ExchangeMonitorError) as raised:
            monitor.account()
        self.assertNotIn("secret-value", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
