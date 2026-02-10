<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';

mono_session_start();
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header('Location: ../index.php');
    exit;
}

if (!mono_auth_hash_configured()) {
    http_response_code(500);
    echo 'Password hash is not configured. Set app_password_hash in config.local.php';
    exit;
}

$password = '';
if (isset($_POST['password'])) {
    $password = (string)$_POST['password'];
}

if (mono_attempt_login($password)) {
    header('Location: ../index.php');
    exit;
}
header('Location: ../index.php?login_error=1');
exit;
