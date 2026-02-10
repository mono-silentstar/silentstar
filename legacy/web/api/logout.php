<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header('Location: ../index.php');
    exit;
}

mono_logout();
header('Location: ../index.php');
exit;
