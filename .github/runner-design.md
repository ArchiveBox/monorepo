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
- **Ordinary Linux tests are eligible by default.** Genuine hosted-only
  requirements belong in a `# ci-runner: hosted` test-file header, with a reason.
  File discovery preserves those requirements through renames. Investigate
  workload, container limits, storage and contention when a test times out;
  a timeout alone does not establish that the NAS is unsuitable. Preserve the
  test's correctness assertions while investigating.
- **Use both pools.** Discovery assigns a bounded share of eligible jobs to the
  existing availability check and leaves the remainder hosted. The operational
  `UGNAS_CI_MAX_JOBS` setting controls that share. In ArchiveBox,
  `UGNAS_CI_MIN_IDLE` separately controls the idle workers required by the check:
  queued jobs are not runner slots. Coupling these values limited ugNAS to one
  wave, leaving it idle while hosted tests waited. Queue multiple waves without
  requiring every worker to be idle, and measure contention before expanding
  further. Do not queue an entire hosted matrix behind a small NAS pool. These
  are capacity settings, not lists of test filenames.
- **Reserve NAS capacity for its other services.** The CI pool must leave about
  20% CPU headroom for Plex and TrueNAS spikes. Persist resource limits through
  TrueNAS app configuration; a live `docker update` alone is lost on redeploy.
  The catalog's CPU field accepts whole numbers, so fractional quotas require
  its supported custom Compose app configuration, preserving the stock image
  and entrypoint. Do not shrink each worker below one effective CPU without
  considering the application's admission policy: ArchiveBox intentionally
  clamps concurrent snapshots to the rounded-up cgroup quota. A quota at or
  below one CPU serializes captures, making overlap acceptance impossible even
  when memory is plentiful. Budget the pool without changing those assertions
  or bypassing application resource checks.
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
