<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';

function mono_complete_flatten_tokens(mixed $input): array
{
    if ($input === null) {
        return [];
    }
    if (is_array($input)) {
        $all = [];
        foreach ($input as $item) {
            $all = array_merge($all, mono_complete_flatten_tokens($item));
        }
        return $all;
    }
    if (is_scalar($input)) {
        $parts = preg_split('/[\s,;|]+/', trim((string)$input));
        return is_array($parts) ? $parts : [];
    }
    return [];
}

function mono_complete_normalize_tags(mixed $input, array $allowed): array
{
    $allowMap = array_fill_keys($allowed, true);
    $out = [];
    foreach (mono_complete_flatten_tokens($input) as $raw) {
        $tag = strtolower(trim((string)$raw));
        if ($tag === '' || !isset($allowMap[$tag])) {
            continue;
        }
        $out[$tag] = true;
    }
    return array_keys($out);
}

function mono_complete_normalize_actor(mixed $actor, string $fallback = 'claude'): string
{
    if (!is_scalar($actor)) {
        return $fallback;
    }
    $candidate = strtolower(trim((string)$actor));
    if ($candidate === '') {
        return $fallback;
    }
    if ($candidate === 'ylhara') {
        $candidate = "y'lhara";
    }
    if (preg_match("/^[a-z0-9_'-]{1,64}$/", $candidate) !== 1) {
        return $fallback;
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
    return in_array($candidate, $allowed, true) ? $candidate : $fallback;
}

try {
    mono_require_method('POST');
    mono_require_bridge_secret();
    mono_init_storage();

    $body = mono_read_json_body();
    $jobId = trim((string)($body['id'] ?? ''));
    if ($jobId === '') {
        mono_json_response(400, [
            'ok' => false,
            'error' => 'missing_job_id',
            'message' => 'id is required',
        ]);
    }

    $status = (string)($body['status'] ?? '');
    if ($status !== 'done' && $status !== 'error') {
        mono_json_response(400, [
            'ok' => false,
            'error' => 'invalid_status',
            'message' => 'status must be done or error',
        ]);
    }

    $replyText = isset($body['reply_text']) ? (string)$body['reply_text'] : null;
    $errorMessage = isset($body['error_message']) ? (string)$body['error_message'] : null;
    $turnId = isset($body['turn_id']) ? (string)$body['turn_id'] : null;
    $localImagePath = isset($body['local_image_path']) ? (string)$body['local_image_path'] : null;
    $actor = $body['actor'] ?? null;
    $tags = $body['tags'] ?? null;
    $contentTags = $body['content_tags'] ?? null;
    $displayTags = $body['display_tags'] ?? null;
    $meta = $body['meta'] ?? null;

    $actorNorm = mono_complete_normalize_actor($actor, 'claude');
    $allTags = mono_complete_normalize_tags($tags, ['plan', 'secret', 'say', 'rp', 'nr']);
    $contentTagsNorm = mono_complete_normalize_tags($contentTags, ['plan', 'secret']);
    $displayTagsNorm = mono_complete_normalize_tags($displayTags, ['say', 'rp', 'nr']);
    if ($contentTagsNorm === [] && $allTags !== []) {
        $contentTagsNorm = array_values(array_intersect($allTags, ['plan', 'secret']));
    }
    if ($displayTagsNorm === [] && $allTags !== []) {
        $displayTagsNorm = array_values(array_intersect($allTags, ['say', 'rp', 'nr']));
    }
    if ($allTags === []) {
        $allTags = mono_complete_normalize_tags(array_merge($contentTagsNorm, $displayTagsNorm), ['plan', 'secret', 'say', 'rp', 'nr']);
    }

    $metaNorm = null;
    if (is_array($meta)) {
        $metaNorm = $meta;
    } elseif ($meta !== null) {
        $metaNorm = ['bridge_meta' => $meta];
    } else {
        $metaNorm = [];
    }
    $existingClaude = is_array($metaNorm['claude'] ?? null) ? $metaNorm['claude'] : [];
    $metaNorm['claude'] = array_merge($existingClaude, [
        'actor' => $actorNorm,
        'content_tags' => $contentTagsNorm,
        'display_tags' => $displayTagsNorm,
        'tags' => $allTags,
    ]);

    $final = mono_with_lock('jobs', static function () use (
        $jobId,
        $status,
        $replyText,
        $errorMessage,
        $turnId,
        $localImagePath,
        $metaNorm
    ): ?array {
        $current = mono_get_job($jobId);
        if (!is_array($current)) {
            return null;
        }
        $currentStatus = (string)($current['status'] ?? '');
        if ($currentStatus === 'done' || $currentStatus === 'error') {
            return $current;
        }

        $updated = mono_finish_job(
            $jobId,
            $status,
            $replyText,
            $errorMessage,
            $turnId,
            $localImagePath,
            $metaNorm
        );
        if (is_array($updated)) {
            mono_delete_temp_upload_for_job($updated);
        }
        return $updated;
    });

    if (!is_array($final)) {
        mono_json_response(404, [
            'ok' => false,
            'error' => 'job_not_found',
            'message' => 'job does not exist',
        ]);
    }

    mono_json_response(200, [
        'ok' => true,
        'id' => $final['id'],
        'status' => $final['status'],
    ]);
} catch (Throwable $e) {
    mono_json_response(500, [
        'ok' => false,
        'error' => 'server_error',
        'message' => $e->getMessage(),
    ]);
}
