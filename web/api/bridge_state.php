<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';

try {
    ss_require_method('GET');
    ss_require_login();

    $state = ss_get_bridge_state();
    $online = ss_bridge_is_online($state);

    ss_json_response(200, [
        'ok'     => true,
        'online' => $online,
        'busy'   => (bool)($state['busy'] ?? false),
        'v'      => 3,
        '_gd'    => function_exists('imagecreatefromjpeg'),
        '_mem'   => ini_get('memory_limit'),
    ]);
} catch (Throwable $e) {
    ss_json_response(500, ['ok' => false, 'error' => $e->getMessage()]);
}
