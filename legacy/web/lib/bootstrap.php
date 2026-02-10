<?php
declare(strict_types=1);

function mono_root_dir(): string
{
    return dirname(__DIR__);
}

function mono_project_root_dir(): string
{
    return dirname(mono_root_dir());
}

function mono_is_absolute_path(string $path): bool
{
    if ($path === '') {
        return false;
    }
    if (str_starts_with($path, '/')) {
        return true;
    }
    if (preg_match('/^[A-Za-z]:[\\\\\\/]/', $path) === 1) {
        return true;
    }
    if (str_starts_with($path, '\\\\')) {
        return true;
    }
    return false;
}

function mono_join_paths(string $base, string $suffix): string
{
    $base = rtrim($base, "/\\");
    $suffix = ltrim($suffix, "/\\");
    return $base . '/' . $suffix;
}

function mono_resolve_repo_path(string $path): string
{
    $value = trim($path);
    if ($value === '') {
        return mono_project_root_dir();
    }

    // Treat /data/... as a repo-relative alias for portability.
    if ($value === '/data' || str_starts_with($value, '/data/')) {
        return mono_join_paths(mono_project_root_dir(), ltrim($value, '/'));
    }

    if (mono_is_absolute_path($value)) {
        return $value;
    }

    return mono_join_paths(mono_project_root_dir(), $value);
}

function mono_load_config(): array
{
    static $cfg = null;
    if (is_array($cfg)) {
        return $cfg;
    }
    $loaded = require mono_root_dir() . '/config.php';
    if (!is_array($loaded)) {
        throw new RuntimeException('config.php must return an array');
    }
    $cfg = $loaded;

    $tz = (string)($cfg['timezone'] ?? 'UTC');
    if ($tz !== '') {
        date_default_timezone_set($tz);
    }
    return $cfg;
}

function mono_cfg(string $key, mixed $default = null): mixed
{
    $cfg = mono_load_config();
    return array_key_exists($key, $cfg) ? $cfg[$key] : $default;
}

function mono_now_iso(): string
{
    return gmdate('c');
}

function mono_data_dir(): string
{
    $configured = trim((string)mono_cfg('data_dir', 'data'));
    if ($configured === '') {
        $configured = 'data';
    }
    return mono_resolve_repo_path($configured);
}

function mono_jobs_dir(): string
{
    return mono_data_dir() . '/jobs';
}

function mono_uploads_tmp_dir(): string
{
    return mono_data_dir() . '/uploads_tmp';
}

function mono_state_dir(): string
{
    return mono_data_dir() . '/state';
}

function mono_ensure_dir(string $dir): void
{
    if (is_dir($dir)) {
        return;
    }
    if (!mkdir($dir, 0700, true) && !is_dir($dir)) {
        throw new RuntimeException('failed to create directory: ' . $dir);
    }
}

function mono_init_storage(): void
{
    mono_ensure_dir(mono_data_dir());
    mono_ensure_dir(mono_jobs_dir());
    mono_ensure_dir(mono_uploads_tmp_dir());
    mono_ensure_dir(mono_state_dir());
}

function mono_json_response(int $status, array $payload): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function mono_require_method(string $method): void
{
    $actual = strtoupper((string)($_SERVER['REQUEST_METHOD'] ?? 'GET'));
    if ($actual !== strtoupper($method)) {
        mono_json_response(405, [
            'ok' => false,
            'error' => 'method_not_allowed',
            'message' => 'expected ' . strtoupper($method),
        ]);
    }
}

function mono_read_json_body(): array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || trim($raw) === '') {
        return [];
    }
    $decoded = json_decode($raw, true);
    if (!is_array($decoded)) {
        mono_json_response(400, [
            'ok' => false,
            'error' => 'invalid_json',
            'message' => 'request body must be valid JSON object',
        ]);
    }
    return $decoded;
}

function mono_random_id(int $bytes = 12): string
{
    return bin2hex(random_bytes($bytes));
}

function mono_with_lock(string $name, callable $fn): mixed
{
    $lockDir = mono_state_dir();
    mono_ensure_dir($lockDir);
    $path = $lockDir . '/' . $name . '.lock';
    $fh = fopen($path, 'c+');
    if ($fh === false) {
        throw new RuntimeException('failed to open lock file: ' . $path);
    }
    try {
        if (!flock($fh, LOCK_EX)) {
            throw new RuntimeException('failed to acquire lock: ' . $path);
        }
        return $fn();
    } finally {
        flock($fh, LOCK_UN);
        fclose($fh);
    }
}

function mono_write_json_atomic(string $path, array $payload): void
{
    $tmp = $path . '.tmp.' . mono_random_id(4);
    $encoded = json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if ($encoded === false) {
        throw new RuntimeException('failed to encode json payload');
    }
    if (file_put_contents($tmp, $encoded . "\n", LOCK_EX) === false) {
        throw new RuntimeException('failed to write temp file: ' . $tmp);
    }
    if (!rename($tmp, $path)) {
        @unlink($tmp);
        throw new RuntimeException('failed to move temp file into place: ' . $path);
    }
}

function mono_read_json_file(string $path): ?array
{
    if (!is_file($path)) {
        return null;
    }
    $raw = file_get_contents($path);
    if ($raw === false) {
        return null;
    }
    $decoded = json_decode($raw, true);
    return is_array($decoded) ? $decoded : null;
}

function mono_normalize_filename(string $name): string
{
    $base = basename($name);
    $sanitized = preg_replace('/[^A-Za-z0-9._-]/', '_', $base);
    $sanitized = $sanitized === null ? '' : $sanitized;
    if ($sanitized === '') {
        return 'upload.bin';
    }
    return $sanitized;
}
