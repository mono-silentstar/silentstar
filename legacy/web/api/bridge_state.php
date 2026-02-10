<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';

try {
    mono_require_login_json();
    $state = mono_get_bridge_state();
    mono_json_response(200, [
        'ok' => true,
        'online' => mono_bridge_is_online($state),
        'busy' => (bool)($state['busy'] ?? false),
        'last_seen_at' => $state['last_seen_at'] ?? null,
        'worker' => $state['worker'] ?? null,
    ]);
} catch (Throwable $e) {
    mono_json_response(500, [
        'ok' => false,
        'error' => 'server_error',
        'message' => $e->getMessage(),
    ]);
}
