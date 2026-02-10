<?php
declare(strict_types=1);

/*
 * Default configuration. Override in config.local.php (same format, gitignored).
 * Environment variables take priority for secrets:
 *   SILENTSTAR_PASSWORD_HASH
 *   SILENTSTAR_BRIDGE_SECRET
 */

$defaults = [
    'app_password_hash'   => '',
    'bridge_shared_secret' => '',
    'session_cookie_name' => 'silentstar_session',
    'bridge_online_ttl_sec' => 8,
    'job_stale_sec'       => 300,
    'data_dir'            => 'data',
    'history_file'        => 'data/history.jsonl',
    'timezone'            => 'UTC',
    'max_upload_bytes'    => 10 * 1024 * 1024,
];

// Load local overrides
$localPath = __DIR__ . '/config.local.php';
if (is_file($localPath)) {
    $local = require $localPath;
    if (is_array($local)) {
        $defaults = array_merge($defaults, $local);
    }
}

// Environment variable overrides for secrets
$envHash = getenv('SILENTSTAR_PASSWORD_HASH');
if (is_string($envHash) && $envHash !== '') {
    $defaults['app_password_hash'] = $envHash;
}
$envSecret = getenv('SILENTSTAR_BRIDGE_SECRET');
if (is_string($envSecret) && $envSecret !== '') {
    $defaults['bridge_shared_secret'] = $envSecret;
}

return $defaults;
