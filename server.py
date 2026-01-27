#!/usr/bin/env python3
import argparse
import json
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
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types


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


def load_config(path: str) -> Tuple[MysqlConfig, Permissions]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    mysql = data.get("mysql", {})
    perms = data.get("permissions", {})
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
    return mysql_cfg, permissions


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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="MySQL MCP server")
    parser.add_argument("--config", default=os.environ.get("DB_MCP_CONFIG", "config.toml"))
    args = parser.parse_args(argv)

    config_path = args.config
    if not os.path.isabs(config_path):
        # Resolve relative to this file by default
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, config_path)

    mysql_cfg, perms = load_config(config_path)
    client = MySQLClient(mysql_cfg, perms)

    server = Server("nowonbun-mariadb-mcp")

    # Define tool registry compatible with this MCP Server API
    TOOL_SPECS: Dict[str, Dict[str, Any]] = {
        "query": {
            "description": (
                "Execute a single SQL statement on the configured MySQL instance. "
                "Permissions (select/insert/update/delete/ddl) are enforced by server config."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "Single SQL statement"},
                    "params": {
                        "type": "object",
                        "description": "Optional named parameters (PyMySQL mapping)",
                    },
                },
                "required": ["sql"],
            },
        },
        "whoami": {
            "description": "Return connection and permission summary (no secrets).",
            "inputSchema": {"type": "object", "properties": {}},
        },
        "health": {
            "description": "Ping the database and return 'ok' if reachable",
            "inputSchema": {"type": "object", "properties": {}},
        },
    }

    @server.list_tools()
    async def list_tools():
        tools: List[types.Tool] = []
        for name, spec in TOOL_SPECS.items():
            tools.append(
                types.Tool(
                    name=name,
                    description=spec.get("description"),
                    inputSchema=spec.get("inputSchema", {"type": "object"}),
                )
            )
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: Dict[str, Any]):
        try:
            if name == "query":
                sql = arguments.get("sql")
                params = arguments.get("params")
                if not isinstance(sql, str) or not sql.strip():
                    return [types.TextContent(type="text", text="ERROR: 'sql' must be a non-empty string")]  # type: ignore[return-value]
                result = client.execute(sql, params)
                text = json.dumps(result, ensure_ascii=False, indent=2)
                return [types.TextContent(type="text", text=text)]
            elif name == "whoami":
                summary = {
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
                return [types.TextContent(type="text", text=json.dumps(summary, ensure_ascii=False, indent=2))]
            elif name == "health":
                client.ping()
                return [types.TextContent(type="text", text="ok")]
            else:
                return [types.TextContent(type="text", text=f"ERROR: Unknown tool '{name}'")]
        except (PermissionError, ValueError) as e:
            return [types.TextContent(type="text", text=f"ERROR: {e}")]
        except Exception as e:  # pragma: no cover
            return [types.TextContent(type="text", text=f"ERROR: {type(e).__name__}: {e}")]

    async def run() -> None:
        async with stdio_server() as (read, write):
            init_opts = server.create_initialization_options()
            await server.run(read, write, init_opts)

    # Run event loop
    import asyncio

    try:
        asyncio.run(run())
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
