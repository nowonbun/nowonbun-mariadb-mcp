데이터베이스에서 디비 확인 mcp는 mcp_servers.mariadb 이다.

핵심 원칙:

1. 기본적으로 조회만 가능하고 데이터를 수정하는 건 금지한다.
2. StockSearcher 프로젝트의 관계된 데이터 베이스는 stock이다.
3. 한국 주식의 관계된 디비는 postfix로 _KR이 있다.
4. 일본 주식의 관계된 디비는 postfix로 _JP가 있다.