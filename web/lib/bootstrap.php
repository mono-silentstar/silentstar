<?php
declare(strict_types=1);

/* --- Paths --- */

function ss_web_root(): string
{
    return dirname(__DIR__);
}

function ss_data_dir(): string
{
    $configured = trim((string)ss_cfg('data_dir', 'data'));
    if ($configured === '') {
        $configured = 'data';
    }
    $path = $configured;
    if (!ss_is_absolute($path)) {
        $path = ss_web_root() . '/' . $path;
    }
    return rtrim($path, '/\\');
}

function ss_jobs_dir(): string
{
    return ss_data_dir() . '/jobs';
}

function ss_uploads_dir(): string
{
    return ss_data_dir() . '/uploads_tmp';
}

function ss_state_dir(): string
{
    return ss_data_dir() . '/state';
}

function ss_history_path(): string
{
    $configured = trim((string)ss_cfg('history_file', 'data/history.jsonl'));
    if ($configured === '') {
        return ss_data_dir() . '/history.jsonl';
    }
    if (!ss_is_absolute($configured)) {
        return ss_web_root() . '/' . $configured;
    }
    return $configured;
}

function ss_is_absolute(string $path): bool
{
    if ($path === '') return false;
    if (str_starts_with($path, '/')) return true;
    if (preg_match('/^[A-Za-z]:[\\\\\\/]/', $path) === 1) return true;
    return false;
}

/* --- Config --- */

function ss_load_config(): array
{
    static $cfg = null;
    if (is_array($cfg)) return $cfg;

    $cfg = require ss_web_root() . '/config.php';
    if (!is_array($cfg)) {
        throw new RuntimeException('config.php must return an array');
    }

    $tz = trim((string)($cfg['timezone'] ?? 'UTC'));
    if ($tz !== '') {
        date_default_timezone_set($tz);
    }
    return $cfg;
}

function ss_cfg(string $key, mixed $default = null): mixed
{
    $cfg = ss_load_config();
    return array_key_exists($key, $cfg) ? $cfg[$key] : $default;
}

/* --- Utilities --- */

function ss_now_iso(): string
{
    return gmdate('c');
}

function ss_random_id(int $bytes = 12): string
{
    return bin2hex(random_bytes($bytes));
}

function ss_ensure_dir(string $dir): void
{
    if (is_dir($dir)) return;
    if (!mkdir($dir, 0700, true) && !is_dir($dir)) {
        throw new RuntimeException('cannot create directory: ' . $dir);
    }
}

function ss_init_storage(): void
{
    ss_ensure_dir(ss_data_dir());
    ss_ensure_dir(ss_jobs_dir());
    ss_ensure_dir(ss_uploads_dir());
    ss_ensure_dir(ss_state_dir());
    ss_ensure_dir(dirname(ss_history_path()));
}

function ss_json_response(int $status, array $payload): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function ss_require_method(string $method): void
{
    $actual = strtoupper((string)($_SERVER['REQUEST_METHOD'] ?? 'GET'));
    if ($actual !== strtoupper($method)) {
        ss_json_response(405, [
            'ok' => false,
            'error' => 'method_not_allowed',
        ]);
    }
}

function ss_read_json_body(): array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || trim($raw) === '') return [];
    $decoded = json_decode($raw, true);
    if (!is_array($decoded)) {
        ss_json_response(400, ['ok' => false, 'error' => 'invalid_json']);
    }
    return $decoded;
}

function ss_write_json_atomic(string $path, array $payload): void
{
    $tmp = $path . '.tmp.' . ss_random_id(4);
    $encoded = json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if ($encoded === false) {
        throw new RuntimeException('json encode failed');
    }
    if (file_put_contents($tmp, $encoded . "\n", LOCK_EX) === false) {
        throw new RuntimeException('write failed: ' . $tmp);
    }
    if (!rename($tmp, $path)) {
        @unlink($tmp);
        throw new RuntimeException('rename failed: ' . $path);
    }
}

function ss_read_json_file(string $path): ?array
{
    if (!is_file($path)) return null;
    $raw = file_get_contents($path);
    if ($raw === false) return null;
    $decoded = json_decode($raw, true);
    return is_array($decoded) ? $decoded : null;
}

function ss_with_lock(string $name, callable $fn): mixed
{
    $lockDir = ss_state_dir();
    ss_ensure_dir($lockDir);
    $fh = fopen($lockDir . '/' . $name . '.lock', 'c+');
    if ($fh === false) {
        throw new RuntimeException('cannot open lock: ' . $name);
    }
    try {
        if (!flock($fh, LOCK_EX)) {
            throw new RuntimeException('cannot acquire lock: ' . $name);
        }
        return $fn();
    } finally {
        flock($fh, LOCK_UN);
        fclose($fh);
    }
}

function ss_normalize_filename(string $name): string
{
    $base = basename($name);
    $sanitized = preg_replace('/[^A-Za-z0-9._-]/', '_', $base);
    return ($sanitized !== null && $sanitized !== '') ? $sanitized : 'upload.bin';
}
