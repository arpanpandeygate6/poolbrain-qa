import pymysql
import pymysql.cursors


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

    def close(self) -> None:
        self.conn.close()
