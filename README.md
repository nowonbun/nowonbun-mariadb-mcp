mariadb DB MCP (MySQL)
======================

Codex에서 사용할 수 있는 경량 MCP 서버입니다. MySQL(MariaDB) 연결 정보를
`config.toml`에 설정하고, 권한(SELECT/INSERT/UPDATE/DELETE/DDL)을 제어할 수 있습니다.

빠른 시작
--------
1) 가상환경 및 의존성 설치
```
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

2) 설정 파일 준비
```
cp config.example.toml config.toml
```
`config.toml`에서 DB 접속 정보와 권한을 수정하세요.

3) 로컬 실행
```
python3 server.py --config ./config.toml
```

Codex에서 실행(로컬)
-------------------
`~/.codex/config.toml` 예시:
```
[mcp_servers.nowonbun-mariadb-mcp]
command = "python3"
args = ["%path%/server.py", "--config", "%path%/config.toml"]
```

Docker로 실행
-----------
이미지 빌드:
```
docker build -t nowonbun-mariadb-mcp:latest .
```

컨테이너 실행:
```
docker run --rm -i \
  -v $(pwd)/config.toml:/config/config.toml:ro \
  -e DB_MCP_CONFIG=/config/config.toml \
  nowonbun-mariadb-mcp:latest
```

Codex에서 실행(Docker)
----------------------
`~/.codex/config.toml` 예시:
```
[mcp_servers.nowonbun-mariadb-mcp]
command = "docker"
args = [
  "run","--rm","-i",
  "-v","%path%/config.toml:/config/config.toml:ro",
  "-e","DB_MCP_CONFIG=/config/config.toml",
  "nowonbun-mariadb-mcp:latest"
]
```

Docker Compose로 실행
---------------------
사전 준비:
```
cp config.example.toml config.toml
```

빌드(최초 1회):
```
docker compose build
```

실행(MCP stdio 위해 `-i` 사용):
```
docker compose run --rm -i nowonbun-mariadb-mcp
```

Codex에서 실행(Compose)
-----------------------
`~/.codex/config.toml` 예시:
```
[mcp_servers.nowonbun-mariadb-mcp]
command = "docker"
args = ["compose", "run", "--rm", "-i", "nowonbun-mariadb-mcp"]
```

설정 파일
---------
`config.example.toml` 참고:
- `[mysql]`: `host`, `port`, `user`, `password`, `database`, `connect_timeout`
- `[permissions]`:
  - `select`: `SELECT` / `SHOW` / `DESCRIBE` / `EXPLAIN`
  - `insert`: `INSERT` (`REPLACE` 포함)
  - `update`: `UPDATE`
  - `delete`: `DELETE`
  - `ddl`: `CREATE` / `ALTER` / `DROP` / `TRUNCATE`
  - `max_rows`: `SELECT` 최대 반환 행 수(0이면 제한 없음)

제공 MCP 도구
-------------
- `query(sql: str, params?: object)`
  - 단일 SQL 문 실행(권한 강제).
  - `params`는 PyMySQL 방식의 파라미터 바인딩을 지원합니다
    (`%(name)s` 또는 `%s`).
  - 반환은 JSON이며 `SELECT`는 `rows`, 그 외는 `rowcount` /
    `last_insert_id`를 포함합니다.
- `whoami()`
  - 연결 정보 및 권한 요약(비밀정보 제외)
- `health()`
  - DB ping으로 연결 확인

주의사항 / 보안
--------------
- 하나의 요청에서 여러 SQL 문은 실행할 수 없습니다.
- 최소 권한 원칙을 권장합니다.
- `DB_MCP_CONFIG` 환경변수로 설정 파일 경로를 지정할 수 있습니다
  (`--config`보다 우선).

문제 해결
---------
- 접속 실패: `mysql.host/port/user/password/database`와 방화벽 설정 확인
- 권한 오류: `permissions.*`와 DB 계정 권한 확인
- 응답이 느림: `permissions.max_rows` 값을 조정
