import base64
import copy
import time
import unittest
from unittest.mock import Mock, patch
from src.github_client import APIError
from src.repository_manager import Manager
from src.security import SafetyError


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.user = {"id":1, "login":"owner"}
        self.run = dict(id="a"*32, actual=time.time(), status="active", phase="claimed",
                        name=None, receipt=None, verified=False, deleted=False)
        self.repo = None
        self.calls = []
        self.sha = "b"*40
        self.api = Mock()
        self.api.request.side_effect = self.request
        self.api.lookup.side_effect = lambda path: copy.deepcopy(self.repo)
        self.guard = Mock()
        self.manager = Manager(self.api, self.user, {"prefix":"auto-calculator-", "delete_after_seconds":0},
                               "owner/controller", "99", self.guard, Mock(), b"calculator", lambda _: self.api)

    def request(self, method, path, body=None, expected=200):
        self.calls.append(method)
        if method == "POST":
            self.assertTrue(body["private"])
            self.repo = dict(id=10, name=body["name"], full_name="owner/"+body["name"],
                             owner=self.user, created_at="2026-01-01T00:00:00Z",
                             description=body["description"], private=True)
            return copy.deepcopy(self.repo)
        if method == "PUT":
            self.assertEqual(base64.b64decode(body["content"]), b"calculator")
            return {"commit":{"sha":self.sha}}
        if method == "DELETE":
            self.repo = None
            return None
        if "/commits/" in path:
            return {"sha":self.sha}
        if "/contents/" in path:
            return {"path":"index.html","content":base64.b64encode(b"calculator").decode()}
        return copy.deepcopy(self.repo)

    def test_complete(self):
        self.manager.execute(self.run)
        self.assertEqual(self.run["status"], "completed")
        self.assertTrue(self.run["verified"] and self.run["deleted"])
        self.assertEqual(self.calls.count("POST"), 1)
        self.assertEqual(self.calls.count("DELETE"), 1)

    def test_collision(self):
        self.repo = {"id":42}
        with self.assertRaises(SafetyError):
            self.manager.execute(self.run)
        self.assertFalse(self.calls)

    def test_ambiguous_create(self):
        self.api.request.side_effect = APIError("network")
        with self.assertRaises(APIError):
            self.manager.execute(self.run)
        self.assertEqual(self.run["phase"], "creating")
        with self.assertRaises(SafetyError):
            self.manager.execute(self.run)
        self.assertEqual(self.api.request.call_count, 1)

    def test_resume_after_verified(self):
        with patch("src.repository_manager.time.sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.execute(self.run)
        self.manager.execute(self.run)
        self.assertEqual(self.calls.count("PUT"), 1)
        self.assertEqual(self.calls.count("DELETE"), 1)

    def test_reconcile_uploaded_commit_without_another_put(self):
        def disconnect(method, *args, **kwargs):
            result = self.request(method, *args, **kwargs)
            if method == "PUT":
                raise APIError("network")
            return result
        self.api.request.side_effect = disconnect
        with self.assertRaises(APIError):
            self.manager.execute(self.run)
        self.api.lookup.side_effect = lambda path: ([{"sha": self.sha}] if "/commits?" in path
                                                   else copy.deepcopy(self.repo))
        self.manager.execute(self.run)
        self.assertEqual(self.calls.count("PUT"), 1)
        self.assertTrue(self.run["verified"] and self.run["deleted"])

    def test_replacement_before_delete(self):
        def change_owner_or_id():
            if self.run["phase"] == "deleting":
                self.repo["id"] = 20
        self.guard.side_effect = change_owner_or_id
        with self.assertRaises(SafetyError):
            self.manager.execute(self.run)
        self.assertNotIn("DELETE", self.calls)

    def test_emergency_stop(self):
        self.guard.side_effect = SafetyError("Disabled")
        with self.assertRaises(SafetyError):
            self.manager.execute(self.run)
        self.assertFalse(self.calls)

    def test_ambiguous_delete(self):
        def drop_reply(method, *args, **kwargs):
            result = self.request(method, *args, **kwargs)
            if method == "DELETE":
                raise APIError("network")
            return result
        self.api.request.side_effect = drop_reply
        with self.assertRaises(APIError):
            self.manager.execute(self.run)
        with self.assertRaises(SafetyError):
            self.manager.execute(self.run)
        self.assertEqual(self.calls.count("DELETE"), 1)

