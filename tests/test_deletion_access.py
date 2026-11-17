import unittest
from unittest.mock import Mock, patch
from src.deletion_access import DeletionAccess
from src.security import SafetyError


class DeletionScope(unittest.TestCase):
    @patch("src.deletion_access.app_jwt", return_value="mock-jwt")
    @patch("src.deletion_access.GitHub")
    def test_credential_bound_to_exact_id(self, client, jwt):
        app, scoped = Mock(), Mock()
        client.side_effect = [app, scoped]
        app.request.side_effect = [
            {"id": 22, "account": {"id": 1}, "repository_selection": "all",
             "permissions": {"administration": "write"}}, {"token": "mock-scoped"}]
        scoped.request.return_value = {"total_count": 1, "repositories": [{"id": 123}]}
        access = DeletionAccess({"login": "owner", "id": 1}, "mock-id", "mock-key")
        self.assertIs(access.scoped(123), scoped)
        app.request.assert_called_with("POST", "/app/installations/22/access_tokens",
                                      {"repository_ids": [123], "permissions": {"administration": "write"}},
                                      expected=201)

    @patch("src.deletion_access.GitHub")
    def test_reject_wider_scope(self, client):
        access = DeletionAccess.__new__(DeletionAccess)
        access.app = Mock()
        access.installation_id = 22
        access.app.request.return_value = {"token": "mock"}
        client.return_value.request.return_value = {"total_count": 2, "repositories": [{"id":1},{"id":2}]}
        with self.assertRaises(SafetyError):
            access.scoped(1)

