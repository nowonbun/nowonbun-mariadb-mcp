#!/usr/bin/env python3
import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

import pymysql
from pymysql.cursors import DictCursor

# MCP server primitives
from mcp.server.fastmcp import Context, FastMCP


@dataclass
class Permissions:
    select: bool = True
    insert: bool = False
    update: bool = False
    delete: bool = False
    ddl: bool = False
    max_rows: int = 1000


@dataclass
class MysqlConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    connect_timeout: int = 5


@dataclass
class AuthConfig:
    api_key: str = ""
    header: str = "x-api-key"
    allow_bearer: bool = True


def load_config(path: str) -> Tuple[MysqlConfig, Permissions, AuthConfig]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    mysql = data.get("mysql", {})
    perms = data.get("permissions", {})
    auth = data.get("auth", {})
    mysql_cfg = MysqlConfig(
        host=mysql.get("host", "127.0.0.1"),
        port=int(mysql.get("port", 3306)),
        user=mysql.get("user", "root"),
        password=mysql.get("password", ""),
        database=mysql.get("database", ""),
        connect_timeout=int(mysql.get("connect_timeout", 5)),
    )
    permissions = Permissions(
        select=bool(perms.get("select", True)),
        insert=bool(perms.get("insert", False)),
        update=bool(perms.get("update", False)),
        delete=bool(perms.get("delete", False)),
        ddl=bool(perms.get("ddl", False)),
        max_rows=int(perms.get("max_rows", 1000)),
    )
    api_key = os.environ.get("DB_MCP_API_KEY", auth.get("api_key", ""))
    header = os.environ.get("DB_MCP_API_KEY_HEADER", auth.get("header", "x-api-key"))
    allow_bearer = bool(auth.get("allow_bearer", True))
    auth_cfg = AuthConfig(api_key=str(api_key or ""), header=str(header or "x-api-key"), allow_bearer=allow_bearer)
    return mysql_cfg, permissions, auth_cfg


class MySQLClient:
    def __init__(self, cfg: MysqlConfig, perms: Permissions) -> None:
        self.cfg = cfg
        self.perms = perms
        self._conn: Optional[pymysql.connections.Connection] = None

    def connect(self) -> None:
        if self._conn is not None:
            return
        self._conn = pymysql.connect(
            host=self.cfg.host,
            port=self.cfg.port,
            user=self.cfg.user,
            password=self.cfg.password,
            database=self.cfg.database,
            connect_timeout=self.cfg.connect_timeout,
            charset="utf8mb4",
            autocommit=True,
            cursorclass=DictCursor,
        )

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def ping(self) -> None:
        self.ensure()
        assert self._conn is not None
        self._conn.ping(reconnect=True)

    def ensure(self) -> None:
        if self._conn is None:
            self.connect()

    def classify(self, sql: str) -> str:
        stmt = sql.strip().lstrip("(")  # ignore leading parentheses
        first = re.split(r"\s+", stmt, maxsplit=1)[0].lower()
        # Map synonyms to groups
        if first in {"select", "show", "describe", "desc", "explain"}:
            return "select"
        if first in {"insert", "replace"}:
            return "insert"
        if first == "update":
            return "update"
        if first == "delete":
            return "delete"
        if first in {"create", "alter", "drop", "truncate"}:
            return "ddl"
        # Fallback: treat as read unless obviously mutating
        return first

    def check_permissions(self, kind: str) -> None:
        if kind == "select" and not self.perms.select:
            raise PermissionError("SELECT permission denied")
        if kind == "insert" and not self.perms.insert:
            raise PermissionError("INSERT permission denied")
        if kind == "update" and not self.perms.update:
            raise PermissionError("UPDATE permission denied")
        if kind == "delete" and not self.perms.delete:
            raise PermissionError("DELETE permission denied")
        if kind == "ddl" and not self.perms.ddl:
            raise PermissionError("DDL permission denied")

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # Disallow multiple statements to avoid surprises
        if ";" in sql.strip().rstrip(";"):
            raise ValueError("Multiple statements per call are not allowed")

        kind = self.classify(sql)
        self.check_permissions(kind)

        self.ensure()
        assert self._conn is not None
        with self._conn.cursor() as cur:
            cur.execute(sql, params or None)
            if kind == "select":
                rows = cur.fetchall()
                max_rows = max(0, int(self.perms.max_rows))
                if max_rows:
                    rows = rows[:max_rows]
                return {
                    "type": kind,
                    "rowcount": len(rows),
                    "rows": rows,
                }
            else:
                info = {
                    "type": kind,
                    "rowcount": cur.rowcount,
                }
                try:
                    last_id = cur.lastrowid
                    if last_id is not None:
                        info["last_insert_id"] = last_id
                except Exception:
                    pass
                return info


def _extract_api_key(request: Any, header_name: str, allow_bearer: bool) -> str:
    if request is None:
        return ""
    key = request.headers.get(header_name, "")
    if key:
        return key
    if allow_bearer:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
    return ""


def _check_api_key(ctx: Optional[Context], auth_cfg: AuthConfig) -> Optional[Dict[str, Any]]:
    if not auth_cfg.api_key:
        return None
    if ctx is None:
        return {"error": "unauthorized: missing request context"}
    try:
        request = ctx.request_context.request
    except Exception:
        request = None
    if request is None:
        return None
    provided = _extract_api_key(request, auth_cfg.header, auth_cfg.allow_bearer)
    if provided != auth_cfg.api_key:
        return {"error": "unauthorized: missing or invalid API key"}
    return None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="MySQL MCP server")
    parser.add_argument("--config", default=os.environ.get("DB_MCP_CONFIG", "config.toml"))
    parser.add_argument(
        "--transport",
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        choices=["stdio", "streamable-http"],
        help="Transport to use: stdio or streamable-http",
    )
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8000")))
    parser.add_argument(
        "--stateless-http",
        action="store_true",
        default=os.environ.get("MCP_STATELESS_HTTP", "true").lower() == "true",
        help="Use stateless HTTP mode (recommended for streamable-http)",
    )
    parser.add_argument(
        "--json-response",
        action="store_true",
        default=os.environ.get("MCP_JSON_RESPONSE", "true").lower() == "true",
        help="Use JSON responses instead of SSE (recommended for streamable-http)",
    )
    args = parser.parse_args(argv)

    config_path = args.config
    if not os.path.isabs(config_path):
        # Resolve relative to this file by default
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, config_path)

    mysql_cfg, perms, auth_cfg = load_config(config_path)
    client = MySQLClient(mysql_cfg, perms)

    mcp = FastMCP(
        "nowonbun-mariadb-mcp",
        host=args.host,
        port=args.port,
        stateless_http=args.stateless_http,
        json_response=args.json_response,
    )

    @mcp.tool()
    def query(ctx: Context, sql: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a single SQL statement with permission enforcement."""
        auth_error = _check_api_key(ctx, auth_cfg)
        if auth_error:
            return auth_error
        if not isinstance(sql, str) or not sql.strip():
            return {"error": "sql must be a non-empty string"}
        try:
            return client.execute(sql, params)
        except (PermissionError, ValueError) as e:
            return {"error": str(e)}

    @mcp.tool()
    def whoami(ctx: Context) -> Dict[str, Any]:
        """Return connection and permission summary (no secrets)."""
        auth_error = _check_api_key(ctx, auth_cfg)
        if auth_error:
            return auth_error
        return {
            "mysql": {
                "host": mysql_cfg.host,
                "port": mysql_cfg.port,
                "database": mysql_cfg.database,
                "user": mysql_cfg.user,
            },
            "permissions": {
                "select": perms.select,
                "insert": perms.insert,
                "update": perms.update,
                "delete": perms.delete,
                "ddl": perms.ddl,
                "max_rows": perms.max_rows,
            },
        }

    @mcp.tool()
    def health(ctx: Context) -> str:
        """Ping the database and return 'ok' if reachable."""
        auth_error = _check_api_key(ctx, auth_cfg)
        if auth_error:
            return "unauthorized: missing or invalid API key"
        client.ping()
        return "ok"

    try:
        if args.transport == "streamable-http":
            try:
                mcp.run(
                    transport="streamable-http",
                    host=args.host,
                    port=args.port,
                )
            except TypeError:
                mcp.run(transport="streamable-http")
        else:
            mcp.run(transport="stdio")
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
