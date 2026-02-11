<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';

ss_require_method('POST');
ss_logout();
header('Location: ../');
exit;
