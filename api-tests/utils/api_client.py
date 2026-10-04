import requests

# Login endpoint. The pretend PoolBrain uses this path; check it against the
# internal API reference before pointing the suite at real UAT.
LOGIN_PATH = "auth/login"

# On read-only environments (Preprod, PROD, NPP) only these calls are allowed:
# reads, and the login that gives a smoke test its session (Story 3.1). Add
# another safe call only when the release owner agrees, with the reason.
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
SAFE_CALLS = {("POST", LOGIN_PATH)}


class ReadOnlyError(RuntimeError):
    """A write was attempted on a read-only environment; nothing was sent."""


class ApiClient:
    """Thin wrapper over requests.Session with the base URL and auth set once.

    With read_only=True (Preprod, PROD, NPP) it refuses every call that could
    change data, before any network call.
    """

    def __init__(self, base_url: str, token: str = "", timeout: float = 30, read_only: bool = False, env: str = ""):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.read_only = read_only
        self.env = env
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        method = method.upper()
        if self.read_only and method not in SAFE_METHODS and (method, path.strip("/")) not in SAFE_CALLS:
            raise ReadOnlyError(f"{method} {path} refused: {self.env or 'this environment'} is read-only "
                                "(smoke tests may only read). Nothing was sent.")
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

    def customers(self) -> requests.Response:
        return self.get("customers")

    def create_job(self, name: str, customer_id: int, job_type: str, scheduled_date: str) -> requests.Response:
        """Create a job. scheduled_date is YYYY-MM-DD."""
        return self.post(
            "jobs",
            json={"name": name, "customer_id": customer_id, "job_type": job_type, "scheduled_date": scheduled_date},
        )

    def get_job(self, job_id: int) -> requests.Response:
        return self.get(f"jobs/{job_id}")

    def close(self) -> None:
        self.session.close()
