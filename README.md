# YEKKI 공모 레이더

굿즈·기념품, 예술·전시 지원, 디자인 공모, 창업 지원, 해외 공모전, 레지던시, 지자체 사업 공고를
매일 아침 모아서 하나의 페이지로 보여주는 개인용 도구입니다.

## 어떻게 돌아가나

1. **게시판 수집** (`config/sources.yaml`): 등록한 기관·공모 사이트의 목록 페이지에서 새 글을 찾습니다.
2. **웹 검색 발견** (`config/discovery.yaml`): 정한 요일에 Claude가 웹 검색으로 게시판 밖의 공고를 찾습니다.
3. **본문 읽기**: 새 글의 상세 페이지와 첨부 PDF 공고문을 읽습니다.
4. **AI 정리** (`config/profile.yaml`): Claude가 모집 공고인지, 나와 관련 있는지 판단하고 마감일·자격·지원 규모를 뽑습니다.
5. **검증**: 마감일이 원문에 실제로 적혀 있는지 대조합니다. 맞지 않으면 페이지에 **확인 필요**로 표시합니다.
6. **페이지**: GitHub Pages로 배포됩니다. 관심·지원 상태는 각자의 브라우저에만 저장됩니다.

한 번 판단한 글은 `data/seen.json`에 기록되어 다시 읽지 않으므로, 매일 새 글만 비용이 듭니다.

## 처음 설정 (AI 연결은 둘 중 하나)

**A. Claude 구독으로 (Pro·Max 등, 추가 요금 없음)**
1. 내 컴퓨터에 Claude Code 설치 후 터미널에서 `claude setup-token` 실행 → 브라우저 로그인 → 긴 토큰이 출력됨
2. 저장소 Settings → Secrets and variables → Actions → New repository secret
   이름 `CLAUDE_CODE_OAUTH_TOKEN`, 값에 토큰 붙여넣기
3. 실행할 때마다 구독 사용량이 조금씩 쓰입니다 (가벼운 Haiku 모델 사용)

**B. Claude API 키로 (종량제)**
1. platform.claude.com에서 API 키 발급, 월 한도 설정
2. 같은 위치에 이름 `ANTHROPIC_API_KEY`로 등록

**공통: 페이지 켜기**
저장소 Settings → Pages → Build and deployment의 Source를 **GitHub Actions**로 선택.
그다음 Actions 탭 → daily-radar → Run workflow로 첫 실행. 끝나면 `https://<아이디>.github.io/gongmo-radar/`에서 열립니다.

## 비용

- GitHub Actions, Pages: 공개 저장소라 무료
- 구독 방식(A): 추가 요금 없음, 구독 사용량에서 차감
- API 방식(B): 게시글 읽기는 건당 1원 미만, 웹 검색은 1회 약 $0.01. 기본 설정으로 한 달 몇 달러 수준
- 페이지 아래 **수집 상태**에 매일 사용량이 나옵니다.

## 자주 하는 일

| 하고 싶은 것 | 방법 |
|---|---|
| 게시판 추가 | `config/sources.yaml`에 항목 추가 |
| 수집 실패한 소스 고치기 | 페이지 하단 수집 상태 확인 → 주소나 `link_regex` 수정, 안 되면 `enabled: false` |
| 관심 분야 바꾸기 | `config/profile.yaml` 수정 |
| 웹 검색 요일·주제 바꾸기 | `config/discovery.yaml` 수정 |
| 지금 바로 실행 | Actions 탭 → daily-radar → Run workflow (옵션에 `--discover`를 넣으면 웹 검색도 실행) |

## 로컬에서 실행

```bash
pip install -r requirements.txt
python -m pytest -q                 # 오프라인 테스트
python -m radar.run --dry-run       # AI 없이 새 후보 글만 출력
ANTHROPIC_API_KEY=... python -m radar.run
```
