# Shared by the Ubuntu installer and read-only doctor. Call from repository root.
export PATH="$HOME/.local/bin:$PATH"
# Executable:Ubuntu package. Add machine prerequisites here.
machine_tools=(git:git curl:curl jq:jq rg:ripgrep gh:gh python3:python3 tar:tar xz:xz-utils)
python_series=$(<.python-version)
go_min=$(awk '$1 == "go" {print $2}' services/notifier/go.mod)

node_ok() {
    node -e 'const [a,b] = process.versions.node.split(".").map(Number);
        const supported = (a === 22 && b >= 20) || (a === 24 && b >= 12) || a >= 25;
        process.exit(supported ? 0 : 1)' &&
        npm --version | awk -F. '{exit !($1 >= 9)}'
}

go_ok() {
    local version
    version=$(GOTOOLCHAIN=local go env GOVERSION) &&
        python3 -c 'import sys
def parts(version):
    return tuple(int(n) for n in version.split("."))
sys.exit(parts(sys.argv[1]) < parts(sys.argv[2]))' "${version#go}" "$go_min"
}

uv_ok() {
    uv sync --help | grep -F -- '--locked' >/dev/null &&
        uv sync --help | grep -F -- '--group' >/dev/null
}

compose_ok() {
    docker compose up --help | grep -F -- '--wait ' >/dev/null
}

just_ok() {
    just --no-dotenv --summary >/dev/null
}
