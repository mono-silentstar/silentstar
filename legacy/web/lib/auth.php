<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function mono_session_start(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    $cookieName = (string)mono_cfg('session_cookie_name', 'silentstar_session');
    if ($cookieName !== '') {
        session_name($cookieName);
    }
    $isSecure = !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off';
    session_set_cookie_params([
        'lifetime' => 0,
        'path' => '/',
        'secure' => $isSecure,
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
    session_start();
}

function mono_auth_hash_configured(): bool
{
    $hash = (string)mono_cfg('app_password_hash', '');
    return $hash !== '';
}

function mono_attempt_login(string $password): bool
{
    mono_session_start();
    $hash = (string)mono_cfg('app_password_hash', '');
    if ($hash === '') {
        return false;
    }
    if (!password_verify($password, $hash)) {
        return false;
    }
    $_SESSION['mono_authed'] = true;
    $_SESSION['mono_auth_at'] = time();
    return true;
}

function mono_is_logged_in(): bool
{
    mono_session_start();
    return !empty($_SESSION['mono_authed']);
}

function mono_require_login_json(): void
{
    if (!mono_is_logged_in()) {
        mono_json_response(401, [
            'ok' => false,
            'error' => 'unauthorized',
            'message' => 'login required',
        ]);
    }
}

function mono_logout(): void
{
    mono_session_start();
    $_SESSION = [];
    if (ini_get('session.use_cookies')) {
        $params = session_get_cookie_params();
        setcookie(session_name(), '', time() - 42000, $params['path'], $params['domain'] ?? '', (bool)$params['secure'], (bool)$params['httponly']);
    }
    session_destroy();
}

function mono_require_bridge_secret(): void
{
    $configured = (string)mono_cfg('bridge_shared_secret', '');
    if ($configured === '') {
        mono_json_response(500, [
            'ok' => false,
            'error' => 'bridge_secret_not_configured',
            'message' => 'bridge secret missing',
        ]);
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
        mono_json_response(401, [
            'ok' => false,
            'error' => 'invalid_bridge_secret',
            'message' => 'bridge authentication failed',
        ]);
    }
}
