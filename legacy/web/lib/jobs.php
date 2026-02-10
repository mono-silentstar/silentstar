<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function mono_job_file(string $jobId): string
{
    return mono_jobs_dir() . '/' . $jobId . '.json';
}

function mono_bridge_state_file(): string
{
    return mono_state_dir() . '/bridge.json';
}

function mono_get_bridge_state(): array
{
    mono_init_storage();
    $state = mono_read_json_file(mono_bridge_state_file());
    if (!is_array($state)) {
        return [
            'last_seen_at' => null,
            'busy' => false,
            'worker' => null,
            'updated_at' => null,
        ];
    }
    return [
        'last_seen_at' => $state['last_seen_at'] ?? null,
        'busy' => (bool)($state['busy'] ?? false),
        'worker' => $state['worker'] ?? null,
        'updated_at' => $state['updated_at'] ?? null,
    ];
}

function mono_set_bridge_state(array $state): void
{
    mono_init_storage();
    mono_write_json_atomic(mono_bridge_state_file(), $state);
}

function mono_bridge_is_online(?array $state = null): bool
{
    $state = $state ?? mono_get_bridge_state();
    $lastSeen = (string)($state['last_seen_at'] ?? '');
    if ($lastSeen === '') {
        return false;
    }
    $ts = strtotime($lastSeen);
    if ($ts === false) {
        return false;
    }
    $ttl = (int)mono_cfg('bridge_online_ttl_sec', 8);
    if ($ttl < 1) {
        $ttl = 8;
    }
    return (time() - $ts) <= $ttl;
}

function mono_list_jobs(): array
{
    mono_init_storage();
    $paths = glob(mono_jobs_dir() . '/*.json');
    if (!is_array($paths)) {
        return [];
    }
    sort($paths, SORT_STRING);
    $jobs = [];
    foreach ($paths as $path) {
        $job = mono_read_json_file($path);
        if (is_array($job) && isset($job['id'])) {
            $jobs[] = $job;
        }
    }
    usort($jobs, static function (array $a, array $b): int {
        $aTime = (string)($a['created_at'] ?? '');
        $bTime = (string)($b['created_at'] ?? '');
        return strcmp($aTime, $bTime);
    });
    return $jobs;
}

function mono_find_active_job(): ?array
{
    foreach (mono_list_jobs() as $job) {
        $status = (string)($job['status'] ?? '');
        if ($status === 'queued' || $status === 'running') {
            return $job;
        }
    }
    return null;
}

function mono_get_job(string $jobId): ?array
{
    if (!preg_match('/^[a-f0-9]{16,64}$/', $jobId)) {
        return null;
    }
    return mono_read_json_file(mono_job_file($jobId));
}

function mono_create_job(string $message, ?array $uploadMeta): array
{
    $jobId = mono_random_id(12);
    $now = mono_now_iso();
    $job = [
        'id' => $jobId,
        'status' => 'queued',
        'message' => $message,
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
}

function mono_update_job(string $jobId, callable $mutator): ?array
{
    $path = mono_job_file($jobId);
    $job = mono_read_json_file($path);
    if (!is_array($job)) {
        return null;
    }
    $updated = $mutator($job);
    if (!is_array($updated)) {
        return null;
    }
    $updated['id'] = $jobId;
    $updated['updated_at'] = mono_now_iso();
    mono_write_json_atomic($path, $updated);
    return $updated;
}

function mono_claim_next_job(?string $worker = null): ?array
{
    $jobs = mono_list_jobs();
    foreach ($jobs as $job) {
        $status = (string)($job['status'] ?? '');
        if ($status !== 'queued') {
            continue;
        }
        $jobId = (string)$job['id'];
        $claimed = mono_update_job($jobId, static function (array $row) use ($worker): array {
            if (($row['status'] ?? '') !== 'queued') {
                return $row;
            }
            $row['status'] = 'running';
            $row['claimed_at'] = mono_now_iso();
            if ($worker !== null && $worker !== '') {
                $row['worker'] = $worker;
            }
            return $row;
        });
        if (is_array($claimed) && (string)($claimed['status'] ?? '') === 'running') {
            return $claimed;
        }
    }
    return null;
}

function mono_finish_job(
    string $jobId,
    string $status,
    ?string $replyText,
    ?string $errorMessage,
    ?string $turnId,
    ?string $localImagePath,
    mixed $meta
): ?array {
    return mono_update_job($jobId, static function (array $row) use (
        $status,
        $replyText,
        $errorMessage,
        $turnId,
        $localImagePath,
        $meta
    ): array {
        $row['status'] = $status;
        $row['completed_at'] = mono_now_iso();
        $row['reply_text'] = $replyText;
        $row['error_message'] = $errorMessage;
        $row['turn_id'] = $turnId;
        $row['local_image_path'] = $localImagePath;
        $row['meta'] = $meta;
        return $row;
    });
}

function mono_delete_temp_upload_for_job(array $job): void
{
    if (!isset($job['upload']) || !is_array($job['upload'])) {
        return;
    }
    $path = (string)($job['upload']['host_path'] ?? '');
    if ($path === '') {
        return;
    }
    if (is_file($path)) {
        @unlink($path);
    }
}

function mono_job_has_secret_reply(array $job): bool
{
    $meta = $job['meta'] ?? null;
    if (!is_array($meta)) {
        return false;
    }

    $candidateSets = [];

    $claude = $meta['claude'] ?? null;
    if (is_array($claude)) {
        $candidateSets[] = $claude['content_tags'] ?? null;
        $candidateSets[] = $claude['tags'] ?? null;
    }

    $ingestion = $meta['ingestion'] ?? null;
    if (is_array($ingestion)) {
        $candidateSets[] = $ingestion['claude_tags'] ?? null;
    }

    foreach ($candidateSets as $tags) {
        if (!is_array($tags)) {
            continue;
        }
        foreach ($tags as $tag) {
            if (is_string($tag) && strtolower(trim($tag)) === 'secret') {
                return true;
            }
        }
    }
    return false;
}

function mono_cleanup_stale_active_jobs(): int
{
    $ttl = (int)mono_cfg('job_stale_sec', 300);
    if ($ttl < 30) {
        $ttl = 300;
    }

    $updatedCount = 0;
    foreach (mono_list_jobs() as $job) {
        $status = (string)($job['status'] ?? '');
        if ($status !== 'queued' && $status !== 'running') {
            continue;
        }
        $anchor = (string)($job['claimed_at'] ?? $job['created_at'] ?? '');
        if ($anchor === '') {
            continue;
        }
        $ts = strtotime($anchor);
        if ($ts === false) {
            continue;
        }
        if ((time() - $ts) < $ttl) {
            continue;
        }

        $jobId = (string)($job['id'] ?? '');
        if ($jobId === '') {
            continue;
        }
        $updated = mono_update_job($jobId, static function (array $row): array {
            $row['status'] = 'error';
            $row['error_message'] = 'stale job auto-expired';
            $row['completed_at'] = mono_now_iso();
            return $row;
        });
        if (is_array($updated)) {
            mono_delete_temp_upload_for_job($updated);
            $updatedCount += 1;
        }
    }
    return $updatedCount;
}
