<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';

function mono_claim_flatten_tokens(mixed $input): array
{
    if ($input === null) {
        return [];
    }
    if (is_array($input)) {
        $all = [];
        foreach ($input as $item) {
            $all = array_merge($all, mono_claim_flatten_tokens($item));
        }
        return $all;
    }
    if (is_scalar($input)) {
        $parts = preg_split('/[\s,;|]+/', trim((string)$input));
        return is_array($parts) ? $parts : [];
    }
    return [];
}

function mono_claim_normalize_tags(mixed $input, array $allowed): array
{
    $allowMap = array_fill_keys($allowed, true);
    $out = [];
    foreach (mono_claim_flatten_tokens($input) as $raw) {
        $tag = strtolower(trim((string)$raw));
        if ($tag === '' || !isset($allowMap[$tag])) {
            continue;
        }
        $out[$tag] = true;
    }
    return array_keys($out);
}

function mono_claim_normalize_actor(mixed $actor): ?string
{
    if (!is_scalar($actor)) {
        return null;
    }
    $candidate = strtolower(trim((string)$actor));
    if ($candidate === '') {
        return null;
    }
    if ($candidate === 'ylhara') {
        $candidate = "y'lhara";
    }
    if (preg_match("/^[a-z0-9_'-]{1,64}$/", $candidate) !== 1) {
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
    return in_array($candidate, $allowed, true) ? $candidate : null;
}

try {
    mono_require_method('POST');
    mono_require_bridge_secret();
    mono_init_storage();

    $body = mono_read_json_body();
    $worker = (string)($body['worker'] ?? '');

    $claimed = mono_with_lock('jobs', static function () use ($worker): ?array {
        mono_cleanup_stale_active_jobs();
        return mono_claim_next_job($worker !== '' ? $worker : null);
    });

    if (!is_array($claimed)) {
        mono_json_response(200, [
            'ok' => true,
            'job' => null,
        ]);
    }

    $upload = is_array($claimed['upload'] ?? null) ? $claimed['upload'] : null;
    $meta = is_array($claimed['meta'] ?? null) ? $claimed['meta'] : null;
    $ingestion = is_array($meta['ingestion'] ?? null) ? $meta['ingestion'] : null;

    $actor = mono_claim_normalize_actor($claimed['actor'] ?? null);
    if ($actor === null && is_array($ingestion)) {
        $actor = mono_claim_normalize_actor($ingestion['mono_actor'] ?? null);
    }

    $allTags = mono_claim_normalize_tags($claimed['tags'] ?? null, ['plan', 'secret', 'say', 'rp', 'nr']);
    $contentTags = mono_claim_normalize_tags($claimed['content_tags'] ?? null, ['plan', 'secret']);
    $displayTags = mono_claim_normalize_tags($claimed['display_tags'] ?? null, ['say', 'rp', 'nr']);

    if ($contentTags === [] && is_array($ingestion)) {
        $contentTags = mono_claim_normalize_tags($ingestion['mono_tags'] ?? null, ['plan', 'secret']);
    }
    if ($displayTags === [] && is_array($ingestion)) {
        $displayTags = mono_claim_normalize_tags($ingestion['mono_tags'] ?? null, ['say', 'rp', 'nr']);
    }
    if ($allTags === [] && is_array($ingestion)) {
        $allTags = mono_claim_normalize_tags($ingestion['mono_tags'] ?? null, ['plan', 'secret', 'say', 'rp', 'nr']);
    }
    if ($contentTags === [] && $allTags !== []) {
        $contentTags = array_values(array_intersect($allTags, ['plan', 'secret']));
    }
    if ($displayTags === [] && $allTags !== []) {
        $displayTags = array_values(array_intersect($allTags, ['say', 'rp', 'nr']));
    }
    if ($allTags === []) {
        $allTags = mono_claim_normalize_tags(array_merge($contentTags, $displayTags), ['plan', 'secret', 'say', 'rp', 'nr']);
    }

    mono_json_response(200, [
        'ok' => true,
        'job' => [
            'id' => $claimed['id'],
            'status' => $claimed['status'],
            'message' => (string)($claimed['message'] ?? ''),
            'created_at' => $claimed['created_at'] ?? null,
            'claimed_at' => $claimed['claimed_at'] ?? null,
            'actor' => $actor,
            'content_tags' => $contentTags,
            'display_tags' => $displayTags,
            'tags' => $allTags,
            'has_upload' => $upload !== null,
            'upload' => $upload === null ? null : [
                'original_name' => $upload['original_name'] ?? null,
                'mime_type' => $upload['mime_type'] ?? null,
                'size_bytes' => $upload['size_bytes'] ?? null,
            ],
            'meta' => $meta,
        ],
    ]);
} catch (Throwable $e) {
    mono_json_response(500, [
        'ok' => false,
        'error' => 'server_error',
        'message' => $e->getMessage(),
    ]);
}
