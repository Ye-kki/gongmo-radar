#!/usr/bin/env bash
# 한국 서버(Oracle Cloud 등 Ubuntu)를 공모 레이더 수집 실행기로 등록합니다.
# 사용법:  curl -fsSL https://raw.githubusercontent.com/Ye-kki/gongmo-radar/main/tools/setup-runner.sh | bash -s -- <등록토큰>
# 등록토큰: GitHub 저장소 → Settings → Actions → Runners → New self-hosted runner 화면의 --token 뒤 값 (1시간 유효)
set -euo pipefail
TOKEN="${1:?등록 토큰을 붙여 주세요: ... | bash -s -- <토큰>}"
REPO_URL="https://github.com/Ye-kki/gongmo-radar"
case "$(uname -m)" in
  aarch64|arm64) ARCH=arm64 ;;
  x86_64|amd64)  ARCH=x64 ;;
  *) echo "지원하지 않는 CPU: $(uname -m)"; exit 1 ;;
esac

echo "== 기본 패키지 설치"
sudo apt-get update -y
sudo apt-get install -y curl tar git jq python3 python3-pip python3-venv
sudo timedatectl set-timezone Asia/Seoul || true

VER="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | jq -r .tag_name | sed 's/^v//')"
echo "== GitHub 실행기 내려받기 v$VER ($ARCH)"
mkdir -p "$HOME/actions-runner" && cd "$HOME/actions-runner"
if [ ! -f ./config.sh ]; then
  curl -fsSL -o runner.tgz "https://github.com/actions/runner/releases/download/v${VER}/actions-runner-linux-${ARCH}-${VER}.tar.gz"
  tar xzf runner.tgz && rm runner.tgz
  sudo ./bin/installdependencies.sh
fi

echo "== 저장소에 등록"
./config.sh --unattended --replace --url "$REPO_URL" --token "$TOKEN" \
  --name "korea-$(hostname)" --labels "self-hosted,korea" --work _work

echo "== 서비스로 실행 (재부팅해도 자동 시작)"
sudo ./svc.sh install "$USER"
sudo ./svc.sh start
echo "완료: GitHub 저장소 Settings → Actions → Runners 에서 korea-$(hostname) 가 Idle 이면 성공입니다."
