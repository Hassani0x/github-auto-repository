import json
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class APIError(RuntimeError):
    def __init__(self, status, retry_at=0):
        self.status = status
        self.retry_at = retry_at
        super().__init__(f"GitHub API status {status}")


class GitHub:
    def __init__(self, token):
        if not token:
            raise ValueError("Missing GitHub credential")
        self.token = token
        self.opener = build_opener(NoRedirect)
        self.calls = 0
        self.rate = {}

    def request(self, method, path, body=None, expected=200):
        req = Request("https://api.github.com" + path, method=method,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": "Bearer " + self.token,
                               "Accept": "application/vnd.github+json",
                               "Content-Type": "application/json",
                               "X-Github-Api-Version": "2022-11-28"})
        for attempt in range(3):
            self.calls += 1
            try:
                with self.opener.open(req, timeout=15) as response:
                    self.observe(response.headers)
                    if response.status != expected:
                        raise APIError(response.status)
                    return json.loads(response.read()) if expected != 204 else None
            except HTTPError as exc:
                self.observe(exc.headers)
                delay = 2 ** attempt
                if exc.code in (403, 429):
                    delay = max(delay, int(exc.headers.get("Retry-After", 60)),
                                int(exc.headers.get("X-RateLimit-Reset", 0)) - int(time.time())
                                if self.rate.get("remaining") == "0" else 0)
                if method != "GET" or attempt == 2 or delay > 8 or exc.code not in (429, 500, 502, 503, 504):
                    raise APIError(exc.code, int(time.time()) + delay if exc.code in (429, 403) else 0) from None
            except (URLError, OSError, HTTPException):
                if method != "GET" or attempt == 2:
                    raise APIError("network") from None
                delay = 2 ** attempt
            time.sleep(delay)

    def observe(self, headers):
        self.rate.update({k: headers["X-RateLimit-" + k] for k in ("remaining", "reset", "limit")
                          if headers.get("X-RateLimit-" + k) is not None})

    def lookup(self, path):
        try:
            return self.request("GET", path)
        except APIError as exc:
            if exc.status == 404:
                return None
            raise

