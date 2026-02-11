<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';

try {
    ss_require_method('POST');
    ss_require_login();
    ss_init_storage();

    $message = trim((string)($_POST['message'] ?? ''));
    $actor = ss_normalize_actor($_POST['actor'] ?? null);
    $tags = ss_normalize_tags($_POST['tags'] ?? []);
    $imageFile = is_array($_FILES['image'] ?? null) ? $_FILES['image'] : null;

    $imageProvided = $imageFile !== null
        && (int)($imageFile['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_NO_FILE;

    if ($message === '' && !$imageProvided) {
        ss_json_response(400, ['ok' => false, 'error' => 'empty_message']);
    }

    $job = ss_with_lock('jobs', static function () use (
        $message, $actor, $tags, $imageProvided, $imageFile
    ): array {
        ss_cleanup_stale_jobs();

        $active = ss_find_active_job();
        if (is_array($active)) {
            ss_json_response(409, ['ok' => false, 'error' => 'bridge_busy']);
        }

        $jobId = ss_random_id(12);
        $uploadMeta = null;
        if ($imageProvided && is_array($imageFile)) {
            $uploadMeta = ss_validate_upload($imageFile, $jobId);
        }

        $now = ss_now_iso();
        $job = [
            'id'           => $jobId,
            'status'       => 'queued',
            'message'      => $message,
            'actor'        => $actor,
            'tags'         => $tags,
            'upload'       => $uploadMeta,
            'created_at'   => $now,
            'updated_at'   => $now,
            'claimed_at'   => null,
            'completed_at' => null,
            'reply_text'   => null,
            'display'      => null,
            'reply_actor'  => null,
            'error_message' => null,
            'turn_id'      => null,
        ];
        ss_write_json_atomic(ss_job_file($jobId), $job);
        return $job;
    });

    // Signal the cron worker to wake up immediately
    @touch(ss_state_dir() . '/trigger');

    ss_json_response(200, [
        'ok'     => true,
        'job_id' => $job['id'],
    ]);
} catch (Throwable $e) {
    ss_json_response(500, ['ok' => false, 'error' => $e->getMessage()]);
}
