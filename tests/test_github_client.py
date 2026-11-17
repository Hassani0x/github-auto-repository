import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch
from src.github_client import GitHub, APIError


class Transport(unittest.TestCase):
    def setUp(self):
        self.api = GitHub("mock")
        self.api.opener = Mock()

    def error(self, status, headers=None):
        self.api.opener.open.side_effect = HTTPError("https://example.invalid", status, "", headers or {}, None)

    def test_invalid_auth(self):
        self.error(401)
        with self.assertRaisesRegex(APIError, "401"):
            self.api.request("GET", "/user")
        self.assertEqual(self.api.calls, 1)

    def test_rate_limit(self):
        self.error(429, {"Retry-After":"120"})
        with self.assertRaises(APIError) as caught:
            self.api.request("GET", "/user")
        self.assertGreater(caught.exception.retry_at, 0)
        self.assertEqual(self.api.calls, 1)

    @patch("src.github_client.time.sleep")
    def test_network_retry_reads_only(self, sleep):
        self.api.opener.open.side_effect = URLError("mock disconnect")
        with self.assertRaises(APIError):
            self.api.request("GET", "/user")
        self.assertEqual(sleep.call_count, 2)
        for method in ("POST", "PUT", "DELETE"):
            self.api.calls = 0
            with self.assertRaises(APIError):
                self.api.request(method, "/user/repos")
            self.assertEqual(self.api.calls, 1)

