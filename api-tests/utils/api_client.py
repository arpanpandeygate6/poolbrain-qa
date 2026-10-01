import requests

# Login endpoint. The pretend PoolBrain uses this path; check it against the
# internal API reference before pointing the suite at real UAT.
LOGIN_PATH = "auth/login"


class ApiClient:
    """Thin wrapper over requests.Session with the base URL and auth set once."""

    def __init__(self, base_url: str, token: str = "", timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        return self.session.request(method, f"{self.base_url}/{path.lstrip('/')}", **kwargs)

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def login(self, email: str, password: str) -> requests.Response:
        """Log in and, on success, send the returned token with every later request."""
        response = self.post(LOGIN_PATH, json={"email": email, "password": password})
        if response.ok:
            token = response.json().get("token")
            if token:
                self.session.headers["Authorization"] = f"Bearer {token}"
        return response

    def close(self) -> None:
        self.session.close()
