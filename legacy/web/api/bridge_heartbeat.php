<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';

try {
    mono_require_method('POST');
    mono_require_bridge_secret();
    mono_init_storage();

    $body = mono_read_json_body();
    $busy = (bool)($body['busy'] ?? false);
    $worker = (string)($body['worker'] ?? '');

    mono_with_lock('bridge_state', static function () use ($busy, $worker): void {
        mono_set_bridge_state([
            'last_seen_at' => mono_now_iso(),
            'busy' => $busy,
            'worker' => $worker !== '' ? $worker : null,
            'updated_at' => mono_now_iso(),
        ]);
    });

    mono_json_response(200, [
        'ok' => true,
        'online' => true,
        'busy' => $busy,
    ]);
} catch (Throwable $e) {
    mono_json_response(500, [
        'ok' => false,
        'error' => 'server_error',
        'message' => $e->getMessage(),
    ]);
}
