"""Issue deletion authority bound by GitHub to one immutable repository ID."""
import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from .github_client import GitHub
from .security import require


def encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def app_jwt(client_id, key):
    require(client_id and key, "Missing deletion App credentials")
    now = int(time.time())
    claims = {"iat": now - 60, "exp": now + 480, "iss": client_id}
    signed = encode(b'{"alg":"RS256","typ":"JWT"}') + b"." + encode(json.dumps(claims).encode())
    # Ubuntu's OpenSSL reads a mode-0600 key file. Secrets never appear in argv.
    with tempfile.TemporaryDirectory() as directory:
        pem = Path(directory, "app.pem")
        with pem.open("xb") as output:
            os.chmod(pem, 0o600)
            output.write(key.encode())
        signature = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(pem)],
                                   input=signed, capture_output=True, timeout=10)
    require(signature.returncode == 0, "Invalid deletion App private key")
    return (signed + b"." + encode(signature.stdout)).decode()


class DeletionAccess:
    def __init__(self, user, client_id, key):
        self.app = GitHub(app_jwt(client_id, key))
        self.client = None
        install = self.app.request("GET", "/users/" + user["login"] + "/installation")
        require(install["account"]["id"] == user["id"] and install["repository_selection"] == "all"
                and install["permissions"].get("administration") == "write",
                "Deletion App installation or permissions mismatch")
        self.installation_id = int(install["id"])

    def scoped(self, repository_id):
        result = self.app.request("POST", f"/app/installations/{self.installation_id}/access_tokens",
                                  {"repository_ids": [repository_id],
                                   "permissions": {"administration": "write"}}, expected=201)
        self.client = GitHub(result["token"])
        scope = self.client.request("GET", "/installation/repositories?per_page=2")
        require(scope["total_count"] == 1 and [r["id"] for r in scope["repositories"]] == [repository_id],
                "Deletion credential scope mismatch")
        return self.client

