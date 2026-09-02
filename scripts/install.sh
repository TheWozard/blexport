#!/usr/bin/env bash
set -euo pipefail

repo="TheWozard/blexport"
binary="blexport"
install_dir="${BLEXPORT_INSTALL_DIR:-$HOME/.local/bin}"

case "$(uname -s)" in
    Darwin) os="darwin" ;;
    Linux)  os="linux" ;;
    *) echo "error: unsupported OS $(uname -s) (only macOS and Linux binaries are published)" >&2; exit 1 ;;
esac

case "$(uname -m)" in
    x86_64|amd64)  arch="amd64" ;;
    arm64|aarch64) arch="arm64" ;;
    *) echo "error: unsupported architecture $(uname -m) (only amd64 and arm64 are published)" >&2; exit 1 ;;
esac

asset="${binary}_${os}_${arch}.tar.gz"

echo "Fetching latest release info for ${repo}..."
release_json="$(curl -fsSL "https://api.github.com/repos/${repo}/releases/latest")"

tag="$(printf '%s' "$release_json" | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')"
asset_url="$(printf '%s' "$release_json" | grep -o "\"browser_download_url\": *\"[^\"]*${asset}\"" | sed -E 's/.*"(https:[^"]+)"/\1/')"
checksums_url="$(printf '%s' "$release_json" | grep -o '"browser_download_url": *"[^"]*checksums.txt"' | sed -E 's/.*"(https:[^"]+)"/\1/')"

if [[ -z "$tag" || -z "$asset_url" ]]; then
    echo "error: could not find a release asset named ${asset} for ${repo}" >&2
    exit 1
fi

echo "Installing ${binary} ${tag} (${os}/${arch})..."

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

curl -fsSL "$asset_url" -o "${work_dir}/${asset}"

if [[ -n "$checksums_url" ]]; then
    curl -fsSL "$checksums_url" -o "${work_dir}/checksums.txt"
    (
        cd "$work_dir"
        want="$(grep " ${asset}\$" checksums.txt | awk '{print $1}')"
        got="$(shasum -a 256 "$asset" | awk '{print $1}')"
        if [[ -z "$want" || "$want" != "$got" ]]; then
            echo "error: checksum mismatch for ${asset} (want ${want:-none}, got ${got})" >&2
            exit 1
        fi
    )
fi

tar -xzf "${work_dir}/${asset}" -C "$work_dir" "$binary"

mkdir -p "$install_dir"
mv "${work_dir}/${binary}" "${install_dir}/${binary}"
chmod +x "${install_dir}/${binary}"

echo "Installed ${binary} ${tag} to ${install_dir}/${binary}"

case ":$PATH:" in
    *":${install_dir}:"*) ;;
    *) echo "note: ${install_dir} is not on your \$PATH — add \`export PATH=\"\$PATH:${install_dir}\"\` to your shell profile" ;;
esac
