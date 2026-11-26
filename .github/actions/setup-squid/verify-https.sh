#!/usr/bin/env bash
set -euo pipefail

proxy=$1
ca=$2

# Joining the tailnet does not guarantee a ready HTTPS path. Hosted jobs
# arrive in waves; retry only transient transport failures, with jitter so
# the retries do not create a second synchronized wave.
for attempt in 1 2 3 4; do
  code=0
  result="$(curl --disable --fail --silent --show-error --noproxy '' \
      --connect-timeout 3 --max-time 5 --proxy "$proxy" --cacert "$ca" \
      --output /dev/null \
      --write-out '%{http_code} connect_status=%{http_connect} tcp=%{time_connect}s tls=%{time_appconnect}s first_byte=%{time_starttransfer}s total=%{time_total}s' \
      https://example.com/)" || code=$?
  status=${result%% *}
  # Numeric transport timings distinguish failed TCP, CONNECT, and TLS without
  # logging request headers, certificates, destination, or proxy credentials.
  printf 'Squid attempt %d: curl=%d status=%s %s\n' "$attempt" "$code" "$status" "${result#* }"
  if (( code == 0 )); then
    if [[ "$status" == 200 ]]; then
      echo 'Squid HTTPS check passed.'
      exit 0
    fi
    echo "::error title=Squid check failed::Expected HTTP 200 through Squid, got $status."
    exit 1
  fi

  case "$code" in
    7|28)
      if (( attempt < 4 )); then
        delay=$(( 1 + RANDOM % 3 ))
        echo "Squid HTTPS attempt $attempt hit a transport error (curl $code); retrying in ${delay}s."
        sleep "$delay"
        continue
      fi
      ;;
  esac

  echo "::error title=Squid unavailable::Verified HTTPS through Squid failed (curl $code, attempt $attempt)."
  exit "$code"
done
