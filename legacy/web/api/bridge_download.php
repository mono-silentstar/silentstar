<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';

try {
    mono_require_method('GET');
    mono_require_bridge_secret();

    $jobId = trim((string)($_GET['id'] ?? ''));
    if ($jobId === '') {
        mono_json_response(400, [
            'ok' => false,
            'error' => 'missing_job_id',
            'message' => 'id is required',
        ]);
    }

    $job = mono_get_job($jobId);
    if (!is_array($job)) {
        mono_json_response(404, [
            'ok' => false,
            'error' => 'job_not_found',
            'message' => 'job does not exist',
        ]);
    }

    $upload = is_array($job['upload'] ?? null) ? $job['upload'] : null;
    $path = is_array($upload) ? (string)($upload['host_path'] ?? '') : '';
    if ($path === '' || !is_file($path)) {
        mono_json_response(404, [
            'ok' => false,
            'error' => 'upload_not_found',
            'message' => 'job has no downloadable upload',
        ]);
    }

    $mime = (string)($upload['mime_type'] ?? 'application/octet-stream');
    $name = mono_normalize_filename((string)($upload['original_name'] ?? 'upload.bin'));

    header('Content-Type: ' . $mime);
    header('Content-Length: ' . (string)filesize($path));
    header('Content-Disposition: attachment; filename="' . $name . '"');
    readfile($path);
    exit;
} catch (Throwable $e) {
    mono_json_response(500, [
        'ok' => false,
        'error' => 'server_error',
        'message' => $e->getMessage(),
    ]);
}
