<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';

try {
    ss_require_method('GET');
    ss_require_bridge_secret();
    ss_init_storage();

    $jobId = trim((string)($_GET['id'] ?? ''));
    if ($jobId === '') {
        ss_json_response(400, ['ok' => false, 'error' => 'missing_job_id']);
    }

    $job = ss_get_job($jobId);
    if (!is_array($job)) {
        ss_json_response(404, ['ok' => false, 'error' => 'job_not_found']);
    }

    $upload = $job['upload'] ?? null;
    if (!is_array($upload)) {
        ss_json_response(404, ['ok' => false, 'error' => 'no_upload']);
    }

    $path = (string)($upload['host_path'] ?? '');
    if ($path === '' || !is_file($path)) {
        ss_json_response(404, ['ok' => false, 'error' => 'file_missing']);
    }

    $mime = (string)($upload['mime_type'] ?? 'application/octet-stream');
    $name = (string)($upload['original_name'] ?? 'image.bin');

    header('Content-Type: ' . $mime);
    header('Content-Disposition: attachment; filename="' . $name . '"');
    header('Content-Length: ' . filesize($path));
    readfile($path);
    exit;
} catch (Throwable $e) {
    ss_json_response(500, ['ok' => false, 'error' => $e->getMessage()]);
}
