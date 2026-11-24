#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

normalize() {
  local kind="$1" raw="$2" value
  case "$kind:$raw" in
    "servers:There aren't any DNS Servers set on Ethernet." | \
    "domains:There aren't any Search Domains set on Ethernet.") return 0 ;;
  esac
  [[ -n "$raw" ]] || return 1
  while IFS= read -r value; do
    [[ -n "$value" && "$value" != -* && "$value" != Empty && "$value" != *[[:space:]]* ]] || return 1
    printf '%s\n' "$value"
  done <<<"$raw"
}

read_config() {
  local kind="$1" raw
  if [[ "$kind" == servers ]]; then
    raw="$(networksetup -getdnsservers Ethernet)" || return 1
  else
    raw="$(networksetup -getsearchdomains Ethernet)" || return 1
  fi
  normalize "$kind" "$raw"
}

restore_lines() {
  if [[ -s "$1" ]]; then
    cat -- "$1"
  else
    printf '%s\n' Empty
  fi
}

restore_values() {
  local setter="$1" file="$2" value
  [[ -f "$file" ]] || return 1
  local values=()
  while IFS= read -r value; do
    values+=("$value")
  done < <(restore_lines "$file")
  networksetup "$setter" Ethernet "${values[@]}"
}

main() {
  case "$1" in
    save)
      # Preserve old behavior for hostnames and other transports potentially
      # relying on MagicDNS. Only the existing IPv4 HTTP proxy needs this.
      [[ "$SQUID_PROXY" =~ ^http://[0-9]{1,3}(\.[0-9]{1,3}){3}:[0-9]+/?$ ]] || return 0
      local saved
      saved="$(mktemp -d "$RUNNER_TEMP/macos-dns.XXXXXX")"
      read_config servers >"$saved/servers"
      read_config domains >"$saved/domains"
      printf 'state=%s\ntailscale-args=--accept-dns=false\n' "$saved" >>"$GITHUB_OUTPUT"
      ;;
    restore)
      local failed=0
      restore_values -setdnsservers "$DNS_STATE_DIR/servers" || failed=1
      restore_values -setsearchdomains "$DNS_STATE_DIR/domains" || failed=1
      [[ "$failed" == 0 ]]
      read_config servers | cmp -s - "$DNS_STATE_DIR/servers"
      read_config domains | cmp -s - "$DNS_STATE_DIR/domains"
      ;;
    *) return 2 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
