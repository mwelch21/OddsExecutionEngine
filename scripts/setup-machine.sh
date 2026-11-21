#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
die() { echo "setup-machine: $*" >&2; exit 1; }
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || die 'Requires Ubuntu 24.04 x86_64.'
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 24.04 ]] || die 'Requires Ubuntu 24.04.'
(( EUID != 0 )) || die 'Run as the development user. The installer calls sudo for machine changes.'
source scripts/lib/bootstrap-tools.sh
trap 'echo "Machine setup failed at line $LINENO. Correct the error and rerun bootstrap." >&2' ERR

apt_updated=false
install_packages() {
    (( $# )) || return 0
    echo "sudo required for Ubuntu packages: $*"
    if ! $apt_updated; then
        sudo apt-get update
        apt_updated=true
    fi
    sudo apt-get install -y --no-remove --no-install-recommends "$@"
}

packages=()
for entry in "${machine_tools[@]}"; do
    command -v "${entry%:*}" >/dev/null || packages+=("${entry#*:}")
done
command -v "python$python_series" >/dev/null || packages+=("python$python_series")
dpkg-query -W -f='${Status}' ca-certificates 2>/dev/null | grep -q 'ok installed' || packages+=(ca-certificates)
install_packages "${packages[@]}"

bin="$HOME/.local/bin"
mkdir -p "$bin"
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
fetch() { curl --proto '=https' -fsSL --retry 3 "$1" -o "$2"; }
# Publish complete versioned archives. Only replace links owned by this installer.
store="$HOME/.local/share/oddscafe"
publish_tool() {
    local dir=$1 exe
    shift
    mkdir -p "$store"
    if [[ ! -d $store/$dir ]]; then
        mv "$tmp/$dir" "$store/$dir"
    fi
    for exe in "$@"; do
        if [[ -e $bin/$exe || -L $bin/$exe ]]; then
            [[ $(readlink "$bin/$exe") == "$store/"* ]] ||
                die "Existing $bin/$exe needs updating by its owner."
        fi
        ln -sfn "$store/$dir/bin/$exe" "$bin/$exe"
    done
}

if ! uv_ok 2>/dev/null; then
    fetch https://astral.sh/uv/install.sh "$tmp/uv.sh"
    UV_UNMANAGED_INSTALL="$bin" sh "$tmp/uv.sh"
fi
if ! node_ok 2>/dev/null; then
    base=https://nodejs.org/dist/latest-v22.x
    fetch "$base/SHASUMS256.txt" "$tmp/sums"
    archive=$(awk '$2 ~ /^node-v22\.[0-9]+\.[0-9]+-linux-x64\.tar\.xz$/ {print $2}' "$tmp/sums")
    [[ -n $archive ]] || die 'Node 22 Linux archive missing from upstream checksums.'
    fetch "$base/$archive" "$tmp/$archive"
    (cd "$tmp" && grep -F "  $archive" sums | sha256sum -c - && tar -xf "$archive")
    publish_tool "${archive%.tar.xz}" node npm npx
fi
if ! go_ok 2>/dev/null; then
    fetch 'https://go.dev/dl/?mode=json&include=all' "$tmp/go.json"
    # Latest patch on the module's declared major.minor line.
    file=$(jq -er --arg series "go${go_min%.*}." '[.[] | select(.stable and
        (.version | startswith($series))) | .files[] | select(.os=="linux" and
        .arch=="amd64" and .kind=="archive")][0] | select(.) | [.filename,.sha256] | @tsv' "$tmp/go.json")
    read -r archive digest <<< "$file"
    fetch "https://go.dev/dl/$archive" "$tmp/$archive"
    (cd "$tmp" && echo "$digest  $archive" | sha256sum -c - && tar -xf "$archive")
    mv "$tmp/go" "$tmp/${archive%.tar.gz}"
    publish_tool "${archive%.tar.gz}" go gofmt
fi
if ! just_ok 2>/dev/null; then
    fetch https://just.systems/install.sh "$tmp/just.sh"
    bash "$tmp/just.sh" --to "$bin"
fi
if ! claude --version >/dev/null 2>&1; then
    fetch https://claude.ai/install.sh "$tmp/claude.sh"
    bash "$tmp/claude.sh"
fi
if ! codex --version >/dev/null 2>&1; then
    npm install --global --prefix "$HOME/.local" @openai/codex
fi

packages=()
# Use the same packaging family as an existing Docker CE installation.
if dpkg-query -W -f='${Status}' docker-ce-cli 2>/dev/null | grep -q 'ok installed'; then
    engine_pkg=docker-ce
    compose_pkg=docker-compose-plugin
    buildx_pkg=docker-buildx-plugin
else
    engine_pkg=docker.io
    compose_pkg=docker-compose-v2
    buildx_pkg=docker-buildx
fi
if ! command -v docker >/dev/null || {
    [[ -z ${DOCKER_HOST:-} && $(docker context show) == default ]] &&
        ! command -v dockerd >/dev/null && ! docker info >/dev/null 2>&1
}; then
    packages+=("$engine_pkg")
fi
compose_ok 2>/dev/null || packages+=("$compose_pkg")
docker buildx version >/dev/null 2>&1 || packages+=("$buildx_pkg")
install_packages "${packages[@]}"
if ! docker info >/dev/null 2>&1; then
    [[ -z ${DOCKER_HOST:-} && $(docker context show) == default ]] ||
        die 'Selected Docker endpoint unavailable. Restore that connection and rerun.'
    [[ -d /run/systemd/system ]] || die 'Docker unavailable. Start a local daemon on a systemd host or select a reachable Docker context.'
    echo 'sudo required to start local Docker and grant this developer root-equivalent Docker access.'
    sudo systemctl start docker
    if ! id -nG "$(id -un)" | tr ' ' '\n' | grep -Fxq docker; then
        sudo usermod -aG docker "$(id -un)"
    fi
fi
echo 'Machine setup complete. Ubuntu login shells use ~/.local/bin after a new login.'
