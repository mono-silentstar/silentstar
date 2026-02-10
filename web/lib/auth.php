<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function ss_session_start(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) return;

    $name = (string)ss_cfg('session_cookie_name', 'silentstar_session');
    if ($name !== '') session_name($name);

    $secure = !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off';
    session_set_cookie_params([
        'lifetime' => 0,
        'path'     => '/',
        'secure'   => $secure,
        'httponly'  => true,
        'samesite'  => 'Lax',
    ]);
    session_start();
}

function ss_auth_configured(): bool
{
    return trim((string)ss_cfg('app_password_hash', '')) !== '';
}

function ss_attempt_login(string $password): bool
{
    ss_session_start();
    $hash = trim((string)ss_cfg('app_password_hash', ''));
    if ($hash === '') return false;
    if (!password_verify($password, $hash)) return false;
    $_SESSION['ss_authed'] = true;
    $_SESSION['ss_auth_at'] = time();
    return true;
}

function ss_is_logged_in(): bool
{
    ss_session_start();
    return !empty($_SESSION['ss_authed']);
}

function ss_require_login(): void
{
    if (!ss_is_logged_in()) {
        ss_json_response(401, ['ok' => false, 'error' => 'unauthorized']);
    }
}

function ss_logout(): void
{
    ss_session_start();
    $_SESSION = [];
    if (ini_get('session.use_cookies')) {
        $p = session_get_cookie_params();
        setcookie(
            session_name(),
            '',
            time() - 42000,
            $p['path'],
            $p['domain'] ?? '',
            (bool)$p['secure'],
            (bool)$p['httponly']
        );
    }
    session_destroy();
}

function ss_require_bridge_secret(): void
{
    $configured = trim((string)ss_cfg('bridge_shared_secret', ''));
    if ($configured === '') {
        ss_json_response(500, ['ok' => false, 'error' => 'bridge_secret_not_configured']);
    }

    $provided = '';
    if (isset($_SERVER['HTTP_X_BRIDGE_SECRET'])) {
        $provided = (string)$_SERVER['HTTP_X_BRIDGE_SECRET'];
    }
    if ($provided === '' && function_exists('getallheaders')) {
        $headers = getallheaders();
        if (is_array($headers) && isset($headers['X-Bridge-Secret'])) {
            $provided = (string)$headers['X-Bridge-Secret'];
        }
    }

    if ($provided === '' || !hash_equals($configured, $provided)) {
        ss_json_response(401, ['ok' => false, 'error' => 'invalid_bridge_secret']);
    }
}
