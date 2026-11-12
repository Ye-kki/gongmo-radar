#!/usr/bin/env bash
# 이 Mac을 공모 레이더 수집 실행기로 등록합니다 (한국 IP에서 수집하기 위해).
# 사용법 (터미널에 한 줄):
#   curl -fsSL https://raw.githubusercontent.com/Ye-kki/gongmo-radar/main/tools/setup-runner-mac.sh | bash -s -- <등록토큰>
# 등록토큰: GitHub 저장소 → Settings → Actions → Runners → New self-hosted runner 화면의 --token 뒤 값 (1시간 유효)
# 지우려면: cd ~/actions-runner && ./svc.sh stop && ./svc.sh uninstall && ./config.sh remove --token <제거토큰>
set -euo pipefail
trap 'echo ""; echo "!! $LINENO번째 줄에서 멈췄습니다. 이 화면을 캡처해서 보내 주세요."' ERR
TOKEN="${1:-}"
if [ -z "$TOKEN" ]; then
  echo "등록 토큰이 없습니다. 명령 맨 끝에 토큰을 붙여 주세요:  ... | bash -s -- <토큰>"
  exit 1
fi
REPO_URL="https://github.com/Ye-kki/gongmo-radar"
DIR="$HOME/actions-runner"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "이 스크립트는 Mac용입니다. Linux 서버는 tools/setup-runner.sh 를 쓰세요."; exit 1
fi
case "$(uname -m)" in
  arm64)  ARCH=arm64 ;;   # Apple 칩(M1~)
  x86_64) ARCH=x64 ;;     # 인텔 Mac
  *) echo "지원하지 않는 CPU: $(uname -m)"; exit 1 ;;
esac

echo "== 1/4 개발 도구 확인"
if ! xcode-select -p >/dev/null 2>&1 || ! git --version >/dev/null 2>&1; then
  echo "git이 없어서 Apple 명령어 도구 설치 창을 띄웁니다."
  echo "창에서 '설치'를 누르고, 끝나면 이 명령을 다시 붙여 넣어 주세요."
  xcode-select --install || true
  exit 1
fi

echo "== 2/4 GitHub 실행기 내려받기"
# 최신 릴리스 페이지가 넘겨주는 주소(.../tag/v2.xxx.x)에서 버전만 꺼냅니다.
LATEST_URL="$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/actions/runner/releases/latest || true)"
VER="${LATEST_URL##*/v}"
case "$VER" in
  [0-9]*.[0-9]*) ;;
  *) # 두 번째 방법: GitHub API (파이프 없이 읽어서 중간에 끊기지 않게)
     JSON="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest || true)"
     VER="$(sed -nE '/"tag_name"/{s/.*"tag_name": *"v([^"]+)".*/\1/p;q;}' <<<"$JSON")" ;;
esac
case "$VER" in
  [0-9]*.[0-9]*) echo "   버전 v$VER" ;;
  *) echo "실행기 버전을 확인하지 못했습니다. 인터넷 연결을 확인하고 다시 실행해 주세요."; exit 1 ;;
esac
mkdir -p "$DIR" && cd "$DIR"
if [ ! -f ./config.sh ]; then
  curl -fsSL -o runner.tgz \
    "https://github.com/actions/runner/releases/download/v${VER}/actions-runner-osx-${ARCH}-${VER}.tar.gz"
  tar xzf runner.tgz && rm runner.tgz
fi

echo "== 3/4 저장소에 등록"
# 이미 등록된 적이 있으면 서비스부터 내리고 다시 등록합니다.
if [ -f ./.runner ]; then ./svc.sh stop >/dev/null 2>&1 || true; ./svc.sh uninstall >/dev/null 2>&1 || true; fi
./config.sh --unattended --replace --url "$REPO_URL" --token "$TOKEN" \
  --name "korea-mac" --labels "self-hosted,korea,macos" --work _work

echo "== 4/4 자동 실행 설정 (로그인하면 자동 시작, 꺼지면 1분 뒤 다시 켜짐)"
# 인터넷이 오래 끊기면 실행기가 스스로 꺼지는 일이 있어서 KeepAlive로 다시 켜지게 합니다.
T=./bin/actions.runner.plist.template
if ! grep -q KeepAlive "$T"; then
  perl -0pi -e 's#(<key>RunAtLoad</key>\s*<true/>)#$1\n    <key>KeepAlive</key>\n    <true/>\n    <key>ThrottleInterval</key>\n    <integer>60</integer>#' "$T"
fi
rm -f ~/Library/LaunchAgents/actions.runner.*gongmo-radar*.plist
./svc.sh install
./svc.sh start

echo ""
echo "완료! GitHub 저장소 Settings → Actions → Runners 에서 korea-mac 이 Idle(초록)이면 성공입니다."
echo "Mac이 잠들어 있던 시간의 수집은 깨어나면 이어서 실행됩니다 (최대 24시간 대기)."
