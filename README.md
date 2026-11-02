# YEKKI 공모 레이더

굿즈·기념품, 예술·전시 지원, 디자인 공모, 창업 지원, 해외 공모전, 레지던시, 지자체 사업 공고(**작가·공모전** 탭)와
청년·주거 등 생활 지원 공고(**생활 지원** 탭)를 매일 아침 모아서 보여주는 개인용 도구입니다.

## 어떻게 돌아가나

1. **게시판 수집** (`config/sources.yaml`): 등록한 기관·공모 사이트의 목록 페이지에서 새 글을 찾습니다.
   `board: life`인 소스는 생활 지원 탭으로 갑니다.
   **기관 홈페이지** (`config/orgs.yaml`, 문화재단·미술관 117곳): 홈페이지에서 공지·공모 게시판을 코드로 자동으로 찾아
   2주마다 갱신합니다. 못 찾은 곳은 수집 상태에 0건으로 뜨며, 그 기관에 `board_url:`을 적어 주면 됩니다.
2. **웹 검색 발견** (`config/discovery.yaml`): 정한 요일에 Claude가 웹 검색으로 게시판 밖의 공고를 찾습니다.
3. **본문 읽기 + 코드 거르기**: 새 글의 상세 페이지와 첨부 PDF 공고문을 읽고, 채용·결과발표·행사 안내처럼
   모집이 아닌 글은 Claude에게 보내기 전에 코드로 버립니다.
4. **날짜 변경 감시**: 마감 전 공고는 매일 다시 열어 날짜 부분만 비교하고, 바뀐 공고만 Claude가 다시 읽습니다.
5. **AI 정리** (6건씩 묶어서 한 번에) (`config/profile.yaml`): Claude가 모집 공고인지, 나와 관련 있는지 판단하고 마감일·자격·지원 규모를 뽑습니다.
6. **검증**: 마감일이 원문에 실제로 적혀 있는지 대조합니다. 맞지 않으면 페이지에 **확인 필요**로 표시합니다.
7. **페이지**: GitHub Pages로 배포됩니다. 관심·지원 상태는 각자의 브라우저에만 저장됩니다.

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

**선택: 생활 지원 개인 조건 (비공개)**
같은 위치에 이름 `RADAR_LIFE_PROFILE`로 나이·거주 지역·주거 형태·관심 지원을 한두 줄로 적어 두면
생활 지원 공고를 그 조건에 맞춰 판단합니다. secret이라 저장소에는 공개되지 않습니다.

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
| 게시판 추가 | `config/sources.yaml`에 항목 추가 (생활 지원이면 `board: life`) |
| 문화재단 게시판 주소 직접 지정 | `config/orgs.yaml`의 해당 기관에 `board_url:` 추가, 끄려면 `enabled: false` |
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

## 한국 IP에서 수집하기 (내 Mac을 실행기로)

해외 접속을 막는 국내 사이트를 읽으려면 수집을 한국에 있는 컴퓨터에서 돌립니다.

1. 저장소 **Settings → Actions → Runners → New self-hosted runner** 에서 `--token` 뒤의 값을 복사합니다 (1시간 유효).
2. Mac 터미널에 붙여 넣습니다:
   `curl -fsSL https://raw.githubusercontent.com/Ye-kki/gongmo-radar/main/tools/setup-runner-mac.sh | bash -s -- <토큰>`
3. **Settings → Secrets and variables → Actions → Variables** 에 `RUNNER` = `self-hosted` 를 추가합니다.

Mac이 꺼져 있거나 잠든 동안의 수집은 깨어나면 실행됩니다 (최대 24시간 대기). 되돌리려면 `RUNNER` 변수를 지우면 됩니다.
