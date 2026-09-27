# Why ugNAS CI is set up this way

Read this before changing self-hosted runner routing or provisioning. This is
decision history, not an inventory: inspect GitHub runner status, repository
variables, workflows, and TrueNAS app configuration for current settings.

- **Extra capacity, not a separate CI platform.** Stock Docker runner containers
  avoid maintaining a clone of GitHub's enormous hosted image. Tests use the same
  commands on both. Missing tools or identity files exposed real portability bugs
  in ArchiveBox; fix those through existing app/provider helpers rather than
  adding runner-only packages or mounting a host machine ID. Reconsider an image
  change only for a demonstrated infrastructure requirement.
- **Keep the stock entrypoint, including its init process.** A canary that bypassed
  `dumb-init` accumulated orphaned Chrome processes and produced misleading cleanup
  failures. Test proposed changes through the real runner lifecycle.
- **Availability is checked on GitHub-hosted compute.** Putting discovery on ugNAS
  would strand the workflow when the NAS is down. The existing fallback selects
  hosted compute when NAS capacity is unavailable or its status API fails. This
  is a scheduling-time decision, not failover after a job starts; a race after
  selection remains. Hosted discovery itself can queue. Do not claim NAS solves
  that wait or add a second scheduler merely to avoid it.
- **Eligibility is deliberately conservative.** Opt in existing Linux matrix
  cells after real stock-container acceptance under concurrent load. One isolated
  pass is insufficient: the CLI list million-row test passed alone but exceeded
  its existing deadline under NAS contention. Keep it hosted until concurrent
  evidence changes that conclusion; don't relax its assertion or timeout. Recheck
  allowlists when test names change instead of copying names into this document.
- **Trusted branch jobs only.** These workers share a private network and persist
  between jobs. Public PR code must remain hosted. Staging acceptance credentials
  belong in a branch-restricted GitHub environment, not runner mounts; its SSH
  key is restricted to the fixed acceptance entrypoint. Never reuse an operator's
  unrestricted key. Environment restrictions do not make untrusted code safe in
  a trusted workflow context.
- **No host Docker socket by default.** It grants control over the NAS and its
  other services. Existing package/test offloads don't require it. Docker-build
  offload needs separate evidence that its isolation and performance justify the
  extra machinery; spare NAS capacity alone is not that evidence.
- **Preserve the dependency cascade.** Runner placement adds capacity without
  changing publication gates, test coverage, or dependency ordering. Measure push
  through downstream publication, separating queue time from execution time.
  A twofold speedup was aspirational, not a reason to complicate the design.

TrueNAS owns app configuration; editing generated Compose files creates drift
that app updates overwrite. Use its supported app configuration interface.
Container redeployment replaces local state; keep job scratch data in
`RUNNER_TEMP`, not shared fixed paths.

Update this file only when a decision or its supporting evidence changes. Remove
constraints when their stated reason no longer applies; don't append status logs,
worker counts, resource limits, package versions, or lists of successful runs.
