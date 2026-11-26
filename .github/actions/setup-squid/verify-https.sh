#!/usr/bin/env bash
set -euo pipefail

proxy=$1
ca=$2

# Joining the tailnet does not guarantee a ready HTTPS path. Hosted jobs
# arrive in waves; retry only transient transport failures, with jitter so
# the retries do not create a second synchronized wave.
for attempt in 1 2 3 4; do
  if status="$(curl --disable --fail --silent --show-error --noproxy '' \
      --connect-timeout 3 --max-time 5 --proxy "$proxy" --cacert "$ca" \
      --output /dev/null --write-out '%{http_code}' https://example.com/)"; then
    if [[ "$status" == 200 ]]; then
      echo 'Squid HTTPS check passed.'
      exit 0
    fi
    echo "::error title=Squid check failed::Expected HTTP 200 through Squid, got $status."
    exit 1
  else
    code=$?
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
