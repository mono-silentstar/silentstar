<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';

try {
    ss_require_method('POST');
    ss_require_bridge_secret();
    ss_init_storage();

    $body = ss_read_json_body();
    $busy = (bool)($body['busy'] ?? false);
    $worker = (string)($body['worker'] ?? '');

    ss_set_bridge_state([
        'last_seen_at' => ss_now_iso(),
        'busy'         => $busy,
        'worker'       => $worker !== '' ? $worker : null,
    ]);

    ss_json_response(200, ['ok' => true]);
} catch (Throwable $e) {
    ss_json_response(500, ['ok' => false, 'error' => $e->getMessage()]);
}
