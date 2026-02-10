<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';

try {
    ss_require_method('POST');

    $password = (string)($_POST['password'] ?? '');
    if ($password === '' || !ss_attempt_login($password)) {
        header('Location: ../?login_error=1');
        exit;
    }

    header('Location: ../');
    exit;
} catch (Throwable $e) {
    header('Location: ../?login_error=1');
    exit;
}
