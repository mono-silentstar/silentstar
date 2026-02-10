<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';

try {
    ss_require_method('POST');
    ss_require_bridge_secret();
    ss_init_storage();

    $body = ss_read_json_body();
    $worker = (string)($body['worker'] ?? '');

    $job = ss_with_lock('jobs', static function () use ($worker): ?array {
        ss_cleanup_stale_jobs();
        return ss_claim_next_job($worker !== '' ? $worker : null);
    });

    if ($job === null) {
        ss_json_response(200, ['ok' => true, 'job' => null]);
    }

    // Attach upload info for the worker
    $hasUpload = is_array($job['upload'] ?? null);

    ss_json_response(200, [
        'ok'  => true,
        'job' => [
            'id'           => $job['id'],
            'message'      => $job['message'] ?? '',
            'actor'        => $job['actor'] ?? 'mono',
            'tags'         => $job['tags'] ?? [],
            'has_upload'   => $hasUpload,
            'upload'       => $hasUpload ? $job['upload'] : null,
            'created_at'   => $job['created_at'] ?? null,
        ],
    ]);
} catch (Throwable $e) {
    ss_json_response(500, ['ok' => false, 'error' => $e->getMessage()]);
}
