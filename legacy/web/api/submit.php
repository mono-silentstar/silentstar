<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';

function mono_flatten_tag_input(mixed $input): array
{
    if ($input === null) {
        return [];
    }
    if (is_array($input)) {
        $all = [];
        foreach ($input as $item) {
            $all = array_merge($all, mono_flatten_tag_input($item));
        }
        return $all;
    }
    if (is_scalar($input)) {
        $parts = preg_split('/[\s,;|]+/', trim((string)$input));
        return is_array($parts) ? $parts : [];
    }
    return [];
}

function mono_normalize_queue_actor(?string $actor): ?string
{
    $v = strtolower(trim((string)$actor));
    if ($v === '') {
        return null;
    }
    if ($v === 'ylhara') {
        $v = "y'lhara";
    }
    if (preg_match("/^[a-z0-9_'-]{1,64}$/", $v) !== 1) {
        return null;
    }
    $allowed = [
        'mono',
        'hasuki',
        'renki',
        'luna',
        'chloe',
        'strah',
        'claude',
        "y'lhara",
    ];
    return in_array($v, $allowed, true) ? $v : null;
}

function mono_normalize_queue_tags(mixed ...$inputs): array
{
    $allowed = [
        'plan' => true,
        'secret' => true,
        'say' => true,
        'rp' => true,
        'nr' => true,
    ];
    $out = [];
    foreach ($inputs as $input) {
        foreach (mono_flatten_tag_input($input) as $raw) {
            $tag = strtolower(trim((string)$raw));
            if ($tag === '' || !isset($allowed[$tag])) {
                continue;
            }
            $out[$tag] = true;
        }
    }
    return array_keys($out);
}

function mono_validate_image_upload(array $file, string $jobId): ?array
{
    $err = (int)($file['error'] ?? UPLOAD_ERR_NO_FILE);
    if ($err === UPLOAD_ERR_NO_FILE) {
        return null;
    }
    if ($err !== UPLOAD_ERR_OK) {
        mono_json_response(400, [
            'ok' => false,
            'error' => 'upload_error',
            'message' => 'upload failed with code ' . $err,
        ]);
    }

    $tmpName = (string)($file['tmp_name'] ?? '');
    if ($tmpName === '' || !is_uploaded_file($tmpName)) {
        mono_json_response(400, [
            'ok' => false,
            'error' => 'invalid_upload',
            'message' => 'uploaded image not found',
        ]);
    }

    $finfo = new finfo(FILEINFO_MIME_TYPE);
    $mime = (string)$finfo->file($tmpName);
    if ($mime === '' || !str_starts_with($mime, 'image/')) {
        mono_json_response(400, [
            'ok' => false,
            'error' => 'invalid_mime',
            'message' => 'only image uploads are allowed',
        ]);
    }

    $origName = mono_normalize_filename((string)($file['name'] ?? 'image.bin'));
    $hostName = $jobId . '__' . $origName;
    $hostPath = mono_uploads_tmp_dir() . '/' . $hostName;
    if (!move_uploaded_file($tmpName, $hostPath)) {
        mono_json_response(500, [
            'ok' => false,
            'error' => 'store_failed',
            'message' => 'failed to persist uploaded image',
        ]);
    }
    @chmod($hostPath, 0600);

    return [
        'original_name' => $origName,
        'mime_type' => $mime,
        'size_bytes' => (int)($file['size'] ?? 0),
        'host_path' => $hostPath,
        'host_name' => $hostName,
    ];
}

try {
    mono_require_method('POST');
    mono_require_login_json();
    mono_init_storage();

    $message = (string)($_POST['message'] ?? '');
    $actor = mono_normalize_queue_actor(isset($_POST['actor']) ? (string)$_POST['actor'] : null) ?? 'mono';
    $tags = $_POST['tags'] ?? null;
    $contentTags = mono_normalize_queue_tags($_POST['content_tags'] ?? null);
    $displayTags = mono_normalize_queue_tags($_POST['display_tags'] ?? null);
    $mergedTags = mono_normalize_queue_tags($tags, $contentTags, $displayTags);
    $contentTags = array_values(array_intersect($mergedTags, ['plan', 'secret']));
    $displayTags = array_values(array_intersect($mergedTags, ['say', 'rp', 'nr']));
    $imageFile = is_array($_FILES['image'] ?? null) ? $_FILES['image'] : null;

    $messageForValidation = trim($message);
    $imageProvided = isset($_FILES['image'])
        && is_array($_FILES['image'])
        && (int)($_FILES['image']['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_NO_FILE;
    if ($messageForValidation === '' && !$imageProvided) {
        mono_json_response(400, [
            'ok' => false,
            'error' => 'empty_turn',
            'message' => 'message or image is required',
        ]);
    }

    $state = mono_get_bridge_state();
    if (!mono_bridge_is_online($state)) {
        mono_json_response(503, [
            'ok' => false,
            'error' => 'bridge_offline',
            'message' => 'local bridge is offline',
        ]);
    }

    $created = mono_with_lock('jobs', static function () use (
        $message,
        $actor,
        $mergedTags,
        $contentTags,
        $displayTags,
        $imageProvided,
        $imageFile
    ): array {
        mono_cleanup_stale_active_jobs();
        $active = mono_find_active_job();
        if (is_array($active)) {
            mono_json_response(409, [
                'ok' => false,
                'error' => 'bridge_busy',
                'message' => 'bridge is currently handling another turn',
                'active_job_id' => $active['id'] ?? null,
            ]);
        }

        $jobId = mono_random_id(12);
        $uploadMeta = null;
        if ($imageProvided) {
            if (!is_array($imageFile)) {
                throw new RuntimeException('image payload missing');
            }
            $uploadMeta = mono_validate_image_upload($imageFile, $jobId);
        }

        $now = mono_now_iso();
        $job = [
            'id' => $jobId,
            'status' => 'queued',
            'message' => $message,
            'actor' => $actor,
            'content_tags' => $contentTags,
            'display_tags' => $displayTags,
            'tags' => $mergedTags,
            'upload' => $uploadMeta,
            'created_at' => $now,
            'updated_at' => $now,
            'claimed_at' => null,
            'completed_at' => null,
            'reply_text' => null,
            'error_message' => null,
            'turn_id' => null,
            'local_image_path' => null,
            'meta' => null,
        ];
        mono_write_json_atomic(mono_job_file($jobId), $job);
        return $job;
    });

    mono_json_response(200, [
        'ok' => true,
        'job_id' => $created['id'],
        'status' => $created['status'],
        'has_image' => is_array($created['upload']),
        'turn' => null,
    ]);
} catch (Throwable $e) {
    mono_json_response(500, [
        'ok' => false,
        'error' => 'server_error',
        'message' => $e->getMessage(),
    ]);
}
