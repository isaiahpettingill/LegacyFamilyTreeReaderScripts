#!/usr/bin/env bash
set -euo pipefail

repository="https://github.com/mdbtools/mdbtools"
ref="dev"
source_dir="${HOME}/.cache/legacy-family-tree-reader/mdbtools"
build_dir=""
prefix="${HOME}/.local"
jobs="$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf '1')"
dry_run=0

usage() {
    printf '%s\n' \
        "Usage: build-mdbtools-llvm.sh [OPTIONS]" \
        "" \
        "  --ref REF             Git branch, tag, or commit (default: dev)" \
        "  --source-dir DIR      Checkout directory" \
        "  --build-dir DIR       Out-of-tree build directory" \
        "  --prefix DIR          Installation prefix (default: ~/.local)" \
        "  --jobs N              Parallel make jobs" \
        "  --dry-run             Print commands without running them" \
        "  -h, --help            Show this help"
}

while (($#)); do
    case "$1" in
        --ref|--source-dir|--build-dir|--prefix|--jobs)
            if (($# < 2)); then
                printf 'error: %s requires a value\n' "$1" >&2
                exit 2
            fi
            option="$1"
            value="$2"
            shift 2
            case "$option" in
                --ref) ref="$value" ;;
                --source-dir) source_dir="$value" ;;
                --build-dir) build_dir="$value" ;;
                --prefix) prefix="$value" ;;
                --jobs) jobs="$value" ;;
            esac
            ;;
        --dry-run) dry_run=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'error: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ -z "$build_dir" ]]; then
    build_dir="${source_dir}/build-llvm"
fi
if [[ ! "$jobs" =~ ^[1-9][0-9]*$ ]]; then
    printf 'error: --jobs must be a positive integer\n' >&2
    exit 2
fi

missing=()
for command in git autoreconf autoconf automake libtoolize make clang clang++ pkg-config; do
    if ! command -v "$command" >/dev/null 2>&1; then
        missing+=("$command")
    fi
done
if ((${#missing[@]})); then
    printf 'error: missing build commands: %s\n' "${missing[*]}" >&2
    printf '%s\n' \
        'Install LLVM/Clang, git, make, autoconf, automake, and libtool.' \
        'mdbtools also requires pkg-config and the GLib development headers.' >&2
    exit 1
fi
if ! pkg-config --exists glib-2.0; then
    printf '%s\n' \
        'error: GLib development files were not found by pkg-config.' \
        'Install the glib2 development package for your operating system.' >&2
    exit 1
fi

run() {
    printf '+'
    printf ' %q' "$@"
    printf '\n'
    if ((dry_run == 0)); then
        "$@"
    fi
}

run_in() {
    local directory="$1"
    shift
    printf '+ cd %q &&' "$directory"
    printf ' %q' "$@"
    printf '\n'
    if ((dry_run == 0)); then
        (cd "$directory" && "$@")
    fi
}

export CC=clang
export CXX=clang++

if [[ -e "$source_dir" ]]; then
    if [[ ! -d "${source_dir}/.git" ]]; then
        printf 'error: source directory is not a git checkout: %s\n' "$source_dir" >&2
        exit 1
    fi
    run git -C "$source_dir" fetch --tags origin
    checkout_ref="$ref"
    if git -C "$source_dir" rev-parse --verify --quiet \
        "refs/remotes/origin/${ref}^{commit}" >/dev/null; then
        checkout_ref="origin/${ref}"
    fi
    run git -C "$source_dir" checkout --detach "$checkout_ref"
else
    run mkdir -p "$(dirname "$source_dir")"
    run git clone "$repository" "$source_dir"
    run git -C "$source_dir" checkout --detach "$ref"
fi

run mkdir -p "$build_dir"
run_in "$source_dir" autoreconf -fi
configure_command=("${source_dir}/configure" "--prefix=${prefix}")
run_in "$build_dir" "${configure_command[@]}"
make_command=(make "-j${jobs}")
run_in "$build_dir" "${make_command[@]}"
run_in "$build_dir" make install
