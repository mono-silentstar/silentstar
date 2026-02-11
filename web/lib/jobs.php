<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

/* --- Identity / Tag validation --- */

define('SS_IDENTITY_TAGS', [
    'hasuki', 'renki', 'luna', 'chloe', 'strah',
    'mono', 'claude', "y'lhara",
]);

define('SS_MONO_IDENTITIES', [
    'hasuki', 'renki', 'luna', 'chloe', 'strah',
]);

define('SS_KNOWLEDGE_TAGS', ['plan', 'pin']);

function ss_normalize_actor(?string $actor): string
{
    $v = strtolower(trim((string)$actor));
    if (in_array($v, SS_MONO_IDENTITIES, true)) return $v;
    return 'mono';
}

function ss_normalize_tags(mixed $input): array
{
    if (!is_array($input)) return [];
    $out = [];
    foreach ($input as $raw) {
        $t = strtolower(trim((string)$raw));
        if ($t !== '' && in_array($t, SS_KNOWLEDGE_TAGS, true) && !in_array($t, $out, true)) {
            $out[] = $t;
        }
    }
    return $out;
}

/* --- Bridge state --- */

function ss_bridge_state_file(): string
{
    return ss_state_dir() . '/bridge.json';
}

function ss_get_bridge_state(): array
{
    ss_init_storage();
    $state = ss_read_json_file(ss_bridge_state_file());
    if (!is_array($state)) {
        return ['last_seen_at' => null, 'busy' => false, 'worker' => null];
    }
    return [
        'last_seen_at' => $state['last_seen_at'] ?? null,
        'busy'         => (bool)($state['busy'] ?? false),
        'worker'       => $state['worker'] ?? null,
    ];
}

function ss_set_bridge_state(array $state): void
{
    ss_init_storage();
    ss_write_json_atomic(ss_bridge_state_file(), $state);
}

function ss_bridge_is_online(?array $state = null): bool
{
    $state = $state ?? ss_get_bridge_state();
    $lastSeen = (string)($state['last_seen_at'] ?? '');
    if ($lastSeen === '') return false;
    $ts = strtotime($lastSeen);
    if ($ts === false) return false;
    $ttl = max(1, (int)ss_cfg('bridge_online_ttl_sec', 8));
    return (time() - $ts) <= $ttl;
}

/* --- Job CRUD --- */

function ss_job_file(string $jobId): string
{
    return ss_jobs_dir() . '/' . $jobId . '.json';
}

function ss_get_job(string $jobId): ?array
{
    if (preg_match('/^[a-f0-9]{16,64}$/', $jobId) !== 1) return null;
    return ss_read_json_file(ss_job_file($jobId));
}

function ss_list_jobs(): array
{
    ss_init_storage();
    $paths = glob(ss_jobs_dir() . '/*.json');
    if (!is_array($paths)) return [];
    sort($paths, SORT_STRING);

    $jobs = [];
    foreach ($paths as $path) {
        $job = ss_read_json_file($path);
        if (is_array($job) && isset($job['id'])) {
            $jobs[] = $job;
        }
    }
    usort($jobs, static fn(array $a, array $b) =>
        strcmp((string)($a['created_at'] ?? ''), (string)($b['created_at'] ?? ''))
    );
    return $jobs;
}

function ss_update_job(string $jobId, callable $mutator): ?array
{
    $path = ss_job_file($jobId);
    $job = ss_read_json_file($path);
    if (!is_array($job)) return null;
    $updated = $mutator($job);
    if (!is_array($updated)) return null;
    $updated['id'] = $jobId;
    $updated['updated_at'] = ss_now_iso();
    ss_write_json_atomic($path, $updated);
    return $updated;
}

function ss_find_active_job(): ?array
{
    foreach (ss_list_jobs() as $job) {
        $st = (string)($job['status'] ?? '');
        if ($st === 'queued' || $st === 'running') return $job;
    }
    return null;
}

function ss_claim_next_job(?string $worker = null): ?array
{
    foreach (ss_list_jobs() as $job) {
        if (($job['status'] ?? '') !== 'queued') continue;
        $jobId = (string)$job['id'];
        $claimed = ss_update_job($jobId, static function (array $row) use ($worker): array {
            if (($row['status'] ?? '') !== 'queued') return $row;
            $row['status'] = 'running';
            $row['claimed_at'] = ss_now_iso();
            if ($worker !== null && $worker !== '') $row['worker'] = $worker;
            return $row;
        });
        if (is_array($claimed) && ($claimed['status'] ?? '') === 'running') {
            return $claimed;
        }
    }
    return null;
}

function ss_cleanup_stale_jobs(): int
{
    $ttl = max(30, (int)ss_cfg('job_stale_sec', 300));
    $count = 0;
    foreach (ss_list_jobs() as $job) {
        $st = (string)($job['status'] ?? '');
        if ($st !== 'queued' && $st !== 'running') continue;
        $anchor = (string)($job['claimed_at'] ?? $job['created_at'] ?? '');
        if ($anchor === '') continue;
        $ts = strtotime($anchor);
        if ($ts === false || (time() - $ts) < $ttl) continue;

        $jobId = (string)($job['id'] ?? '');
        if ($jobId === '') continue;
        $updated = ss_update_job($jobId, static function (array $row): array {
            $row['status'] = 'error';
            $row['error_message'] = 'stale job expired';
            $row['completed_at'] = ss_now_iso();
            return $row;
        });
        if (is_array($updated)) {
            ss_delete_upload($updated);
            $count++;
        }
    }
    return $count;
}

/* --- Uploads --- */

function ss_validate_upload(array $file, string $jobId): ?array
{
    $err = (int)($file['error'] ?? UPLOAD_ERR_NO_FILE);
    if ($err === UPLOAD_ERR_NO_FILE) return null;
    if ($err !== UPLOAD_ERR_OK) {
        ss_json_response(400, ['ok' => false, 'error' => 'upload_failed']);
    }

    $tmpName = (string)($file['tmp_name'] ?? '');
    if ($tmpName === '' || !is_uploaded_file($tmpName)) {
        ss_json_response(400, ['ok' => false, 'error' => 'invalid_upload']);
    }

    $finfo = new finfo(FILEINFO_MIME_TYPE);
    $mime = (string)$finfo->file($tmpName);
    if ($mime === '' || !str_starts_with($mime, 'image/')) {
        ss_json_response(400, ['ok' => false, 'error' => 'images_only']);
    }

    $origName = ss_normalize_filename((string)($file['name'] ?? 'image.bin'));
    $hostName = $jobId . '__' . $origName;
    $hostPath = ss_uploads_dir() . '/' . $hostName;
    if (!move_uploaded_file($tmpName, $hostPath)) {
        ss_json_response(500, ['ok' => false, 'error' => 'store_failed']);
    }
    @chmod($hostPath, 0600);

    return [
        'original_name' => $origName,
        'mime_type'      => $mime,
        'size_bytes'     => (int)($file['size'] ?? 0),
        'host_path'      => $hostPath,
        'host_name'      => $hostName,
    ];
}

function ss_delete_upload(array $job): void
{
    $upload = $job['upload'] ?? null;
    if (!is_array($upload)) return;
    $path = (string)($upload['host_path'] ?? '');
    if ($path !== '' && is_file($path)) @unlink($path);
}
