const { execFileSync } = require('node:child_process');
const { appendFileSync } = require('node:fs');

function api(path) {
    return JSON.parse(execFileSync('gh', ['api', path], { encoding: 'utf8' }));
}

function check(repository, runId, sourceSha, branch, backendRef = '') {
    let backend = '';
    if (backendRef === 'latest-release' || backendRef.startsWith('release:')) {
        backend = backendRef.startsWith('release:') ? backendRef.slice('release:'.length)
            : api('repos/ArchiveBox/ArchiveBox/releases/latest').tag_name.replace(/^v/, '');
        if (!/^\d+\.\d+\.\d+(?:rc\d+)?$/.test(backend)) throw new Error('Invalid backend release');
    } else if (backendRef) {
        backend = api(`repos/ArchiveBox/ArchiveBox/commits/${encodeURIComponent(backendRef)}`).sha;
        if (!/^[a-f0-9]{40}$/.test(backend)) throw new Error('Invalid backend revision');
    }
    if (!/^[a-f0-9]{40}$/.test(sourceSha)) throw new Error('Invalid source revision');
    const key = backend ? `${sourceSha}-${backend}` : sourceSha;
    const current = api(`repos/${repository}/actions/runs/${runId}`);
    const query = `branch=${encodeURIComponent(branch)}&status=success&per_page=100`;
    const candidates = [];
    // Ordinary app build/compatibility runs do not establish a gallery baseline.
    // Dedicated docs/gallery workflows use the same two entry points.
    for (const event of ['schedule', 'workflow_dispatch']) {
        for (let page = 1; ; page++) {
            const runs = api(`repos/${repository}/actions/workflows/${current.workflow_id}/runs?${query}&event=${event}&page=${page}`).workflow_runs;
            candidates.push(...runs.filter(run => String(run.id) !== String(runId) && run.created_at < current.created_at));
            if (runs.length < 100) break;
        }
    }
    let previousKey;
    for (const previous of candidates.sort((a, b) => b.created_at.localeCompare(a.created_at))) {
        for (let page = 1; ; page++) {
            const { jobs, total_count: total } = api(`repos/${repository}/actions/runs/${previous.id}/jobs?filter=latest&per_page=100&page=${page}`);
            // Skipped job names may retain unevaluated expressions. Look past
            // no-change runs to the last executed, successful checkpoint.
            // Failed/cancelled workflows never become the successful baseline.
            const checkpoint = jobs.find(job => /^Scheduled inputs: [a-f0-9]{40}(?:-|$)/.test(job.name) && job.conclusion === 'success');
            if (checkpoint) previousKey = checkpoint.name.slice('Scheduled inputs: '.length);
            if (previousKey || page * 100 >= total) break;
        }
        if (previousKey) break;
    }
    return { changed: String(key !== previousKey), key, backend };
}

if (require.main === module) {
    const result = check(process.env.GITHUB_REPOSITORY, process.env.GITHUB_RUN_ID,
        process.env.GITHUB_SHA, process.env.GITHUB_REF_NAME, process.env.SCHEDULED_BACKEND);
    for (const [name, value] of Object.entries(result)) {
        console.log(`${name}=${value}`);
        appendFileSync(process.env.GITHUB_OUTPUT, `${name}=${value}\n`);
    }
}

module.exports = { check };
