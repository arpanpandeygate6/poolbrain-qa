import time

import pymysql
import pymysql.cursors

from config import REPLICA_TIMEOUTS


class ReadReplica:
    """Read-only SQL access to an Aurora MySQL read replica."""

    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        self.conn = pymysql.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )

    def query(self, sql: str, params: tuple | dict | None = None) -> list[dict]:
        if not sql.lstrip().lower().startswith(("select", "with")):
            raise ValueError("ReadReplica only runs SELECT queries")
        with self.conn.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())

    def wait_for_row(
        self,
        sql: str,
        params: tuple | dict | None = None,
        *,
        purpose: str,
        timeout: float | None = None,
        interval: float = 1.0,
    ) -> dict:
        """Repeat a SELECT until it returns a row, allowing for replica lag; return the first row.

        `purpose` says what the query looks for, for the failure message. The timeout
        defaults to REPLICA_TIMEOUTS["default"] (30 s); pass a REPLICA_TIMEOUTS entry for slower data.
        """
        timeout = REPLICA_TIMEOUTS["default"] if timeout is None else timeout
        deadline = time.monotonic() + timeout
        while True:
            rows = self.query(sql, params)
            if rows:
                return rows[0]
            if time.monotonic() >= deadline:
                raise AssertionError(f"{purpose}: row not found on replica after {timeout:g} s")
            time.sleep(interval)

    def close(self) -> None:
        self.conn.close()
