<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';

try {
    mono_require_method('GET');
    mono_require_login_json();

    $state = mono_get_bridge_state();
    $online = mono_bridge_is_online($state);

    $jobId = trim((string)($_GET['id'] ?? ''));
    if ($jobId === '') {
        mono_json_response(200, [
            'ok' => true,
            'online' => $online,
            'busy' => (bool)($state['busy'] ?? false),
            'last_seen_at' => $state['last_seen_at'] ?? null,
        ]);
    }

    $job = mono_get_job($jobId);
    if (!is_array($job)) {
        mono_json_response(404, [
            'ok' => false,
            'error' => 'job_not_found',
            'message' => 'no job found for id',
        ]);
    }
    $replyHidden = mono_job_has_secret_reply($job);

    mono_json_response(200, [
        'ok' => true,
        'online' => $online,
        'busy' => (bool)($state['busy'] ?? false),
        'job' => [
            'id' => $job['id'],
            'status' => $job['status'],
            'created_at' => $job['created_at'] ?? null,
            'claimed_at' => $job['claimed_at'] ?? null,
            'completed_at' => $job['completed_at'] ?? null,
            'reply_text' => $replyHidden ? null : ($job['reply_text'] ?? null),
            'reply_hidden' => $replyHidden,
            'error_message' => $job['error_message'] ?? null,
            'turn_id' => $job['turn_id'] ?? null,
            'has_image' => is_array($job['upload'] ?? null),
            'local_image_path' => $job['local_image_path'] ?? null,
        ],
    ]);
} catch (Throwable $e) {
    mono_json_response(500, [
        'ok' => false,
        'error' => 'server_error',
        'message' => $e->getMessage(),
    ]);
}
