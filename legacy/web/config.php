<?php
declare(strict_types=1);

$cfg = [
    // Store a password hash, not plaintext. Use password_hash(...).
    'app_password_hash' => '',
    // Shared secret used by the local bridge for host<->local API auth.
    'bridge_shared_secret' => '',
    // Bridge considered online when last heartbeat is within this window.
    'bridge_online_ttl_sec' => 8,
    // Jobs older than this in queued/running state are marked stale.
    'job_stale_sec' => 300,
    // Session cookie behavior.
    'session_cookie_name' => 'silentstar_session',
    // Default timezone for host-side timestamps.
    'timezone' => 'UTC',
    // Repository-relative data root (resolved from project root).
    'data_dir' => 'data',
    // SQLite source-of-truth database used by wake + ingestion.
    'memory_db_path' => 'data/memory.sqlite',
    // Archived image attachments persisted for event history.
    'image_archive_dir' => 'data/img-dump',
];

$localPath = __DIR__ . '/config.local.php';
if (is_file($localPath)) {
    $local = require $localPath;
    if (is_array($local)) {
        $cfg = array_merge($cfg, $local);
    }
}

$envPassHash = getenv('SILENTSTAR_PASSWORD_HASH');
if ((!is_string($envPassHash) || $envPassHash === '')) {
    $envPassHash = getenv('MONO_WEB_PASSWORD_HASH');
}
if (is_string($envPassHash) && $envPassHash !== '') {
    $cfg['app_password_hash'] = $envPassHash;
}
$envBridgeSecret = getenv('SILENTSTAR_BRIDGE_SECRET');
if ((!is_string($envBridgeSecret) || $envBridgeSecret === '')) {
    $envBridgeSecret = getenv('MONO_WEB_BRIDGE_SECRET');
}
if (is_string($envBridgeSecret) && $envBridgeSecret !== '') {
    $cfg['bridge_shared_secret'] = $envBridgeSecret;
}

return $cfg;
