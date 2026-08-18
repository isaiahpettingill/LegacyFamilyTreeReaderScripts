#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd -- "${script_dir}/.." && pwd)"
site_dir="${project_dir}/cloudflare/public"
config="${project_dir}/cloudflare/wrangler.jsonc"
no_password=0
database=""

usage() {
    printf '%s\n' \
        "Usage: deploy-cloudflare.sh DB [--site-dir DIR] [--config FILE] [--no-password]" \
        "" \
        "Build the chunked static site and deploy it to Cloudflare Workers." \
        "" \
        "  --site-dir DIR   Generated site directory (default: cloudflare/public)" \
        "  --config FILE    Wrangler configuration (default: cloudflare/wrangler.jsonc)" \
        "  --no-password    Deploy without changing or deleting Wrangler secrets" \
        "  -h, --help       Show this help"
}

while (($#)); do
    case "$1" in
        --site-dir|--config)
            if (($# < 2)); then
                printf 'error: %s requires a value\n' "$1" >&2
                exit 2
            fi
            option="$1"
            value="$2"
            shift 2
            case "$option" in
                --site-dir) site_dir="$value" ;;
                --config) config="$value" ;;
            esac
            ;;
        --no-password)
            no_password=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --*)
            printf 'error: unknown option: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
        *)
            if [[ -n "$database" ]]; then
                printf 'error: unexpected argument: %s\n' "$1" >&2
                usage >&2
                exit 2
            fi
            database="$1"
            shift
            ;;
    esac
done

if [[ -z "$database" ]]; then
    printf 'error: DB is required\n' >&2
    usage >&2
    exit 2
fi
if [[ ! -f "$database" ]]; then
    printf 'error: database does not exist or is not a file: %s\n' "$database" >&2
    exit 1
fi
if [[ ! -f "$config" ]]; then
    printf 'error: Wrangler configuration does not exist: %s\n' "$config" >&2
    exit 1
fi
if ! command -v npx >/dev/null 2>&1; then
    printf 'error: npx is required to run the pinned Wrangler version\n' >&2
    exit 1
fi

if command -v legacy-family-tree >/dev/null 2>&1; then
    builder=(legacy-family-tree)
elif command -v uv >/dev/null 2>&1; then
    builder=(uv run legacy-family-tree)
else
    printf 'error: install legacy-family-tree or uv before deploying\n' >&2
    exit 1
fi
wrangler=(npx --yes wrangler@4.31.0)

"${builder[@]}" build-site "$database" "$site_dir" --force

if ((no_password == 0)); then
    if ! command -v openssl >/dev/null 2>&1; then
        printf 'error: openssl is required to generate SESSION_SECRET\n' >&2
        exit 1
    fi
    printf '%s\n' 'Enter FAMILY_PASSWORD when Wrangler prompts; input is hidden.'
    "${wrangler[@]}" secret put FAMILY_PASSWORD --config "$config"
    openssl rand -hex 32 | "${wrangler[@]}" secret put SESSION_SECRET --config "$config"
else
    printf '%s\n' \
        'Password secrets will not be changed or deleted.' \
        'If FAMILY_PASSWORD was previously configured, this deployment remains password-protected.' \
        'To disable it explicitly, run:'
    printf '  npx --yes wrangler@4.31.0 secret delete FAMILY_PASSWORD --config %q\n' "$config"
fi

"${wrangler[@]}" deploy --config "$config"
