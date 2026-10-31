const assert = require('node:assert/strict');
const { test } = require('node:test');
const { check } = require('./check.cjs');

// These call the real GitHub API through gh. A missing run exercises the same
// subprocess-error boundary as unavailable history, without a fake API server.
const repository = 'ArchiveBox/abx-plugins';
const sourceSha = '3bf1a6105249c27d52883cb1466048d69a84a317';

test('unavailable optional history requires the complete workflow', () => {
    assert.deepEqual(check(repository, '0', sourceSha, 'main'), {
        changed: 'true', key: sourceSha, backend: '',
    });
});

test('unresolvable required backend still fails', () => {
    assert.throws(() => check(repository, '0', sourceSha, 'main',
        'archivebox-test-nonexistent-backend-ref'), /Command failed/);
});

test('invalid required source still fails', () => {
    assert.throws(() => check(repository, '0', 'not-a-sha', 'main'),
        /Invalid source revision/);
});
