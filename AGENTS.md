# AGENTS.md

## 목적
- 이 저장소는 MariaDB/MySQL용 MCP 서버 프로젝트다.
- 핵심은 단일 SQL 실행, 권한 제한, 설정 기반 연결, 안전한 DB 접근이다.

## 우선순위
1. 보안
2. 권한 제어 정확성
3. 하위 호환성
4. 최소 변경

## 작업 원칙
- 답변과 작업 보고는 항상 한국어로 한다.
- 결론을 먼저 말한다.
- DB 접근 권한과 보안을 기능보다 우선한다.
- 추측으로 SQL 권한 동작을 바꾸지 않는다.
- 변경은 최소 범위로 적용한다.

## 프로젝트 성격
- `server.py`: MCP 서버 본체
- `config.toml`, `config.example.toml`: DB 연결 및 권한 설정
- `docker-compose.yml`, `Dockerfile`: 컨테이너 실행 정의
- `mariadb-mcp.md`, `README.md`: 도구 및 실행 문서
- 주요 도구: `query`, `whoami`, `health`

## 더 엄격한 필수 규칙
- SQL은 1회 호출에 1개 statement만 허용하는 원칙을 유지한다.
- `permissions.*` 해석 변경은 사용자가 명시적으로 요구하지 않으면 하지 않는다.
- `query`의 반환 형식은 기존 클라이언트 호환성을 깨지 않게 유지한다.
- 인증/인가 로직 변경 시 `README.md`, `mariadb-mcp.md`, `config.example.toml` 반영 여부를 반드시 확인한다.
- `env`와 `--config` 우선순위를 바꾸는 수정은 문서 없이 끝내지 않는다.
- 실제 DB 비밀번호/API 키는 어떤 경우에도 저장소에 남기지 않는다.

## 보안 규칙
- 예제 설정은 항상 샘플 값만 사용한다.
- 권한 완화는 사용자가 명시적으로 요청하지 않으면 금지한다.
- 인증 헤더(`x-api-key`, bearer) 변경 시 하위 호환성을 먼저 검토한다.
- 다중 SQL 실행 허용, 권한 우회, 문자열 조합 기반 임시 쿼리 처리는 금지한다.

## 파일 수정 규칙
- `server.py` 수정 시 아래 파일을 같이 점검한다.
  - `README.md`
  - `mariadb-mcp.md`
  - `config.example.toml`
  - `docker-compose.yml` 또는 `Dockerfile`(실행 방식 변경 시)
- 포맷 변경만 하는 대규모 수정은 하지 않는다.

## 검증 규칙
- 최소 검증 절차:
  1. Python 문법 오류 확인
  2. import 오류 확인
  3. 설정 파일 로딩 경로 확인
  4. 핵심 MCP 도구 영향 검토
- 가능하면 권한 허용/차단 분기를 각각 확인한다.
- 실제 DB 실접속 검증을 못 하면 반드시 미검증으로 명시한다.

## 실행/테스트 명령어
```powershell
# 상태 확인
git status --short
Get-Content .\config.example.toml

# 의존성 설치
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 문법/기동 확인
python -m py_compile .\server.py
python .\server.py --config .\config.toml

# Docker
Docker build -t nowonbun-mariadb-mcp:latest .
docker compose build
```

## 금지 사항
- 여러 SQL 문장을 한 번에 허용하도록 바꾸지 않는다.
- 기본 설정에 실제 운영 자격증명을 넣지 않는다.
- 권한 체크를 우회하는 임시 코드를 남기지 않는다.
- DB 실접속 검증 없이 안전하다고 단정하지 않는다.

## 권장 응답 형식
- 결론
- 변경 근거
- 검증 결과
- 보안/운영 리스크
