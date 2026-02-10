<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';
require_once __DIR__ . '/../lib/history.php';

try {
    ss_require_method('GET');
    ss_require_login();

    $jobId = trim((string)($_GET['id'] ?? ''));
    $format = trim((string)($_GET['format'] ?? 'html'));

    // No job ID: return bridge status
    if ($jobId === '') {
        $state = ss_get_bridge_state();
        ss_json_response(200, [
            'ok'     => true,
            'online' => ss_bridge_is_online($state),
            'busy'   => (bool)($state['busy'] ?? false),
        ]);
    }

    $job = ss_get_job($jobId);
    if (!is_array($job)) {
        ss_json_response(404, ['ok' => false, 'error' => 'job_not_found']);
    }

    $st = (string)($job['status'] ?? '');

    // Still in progress — return polling fragment for HTMX
    if ($st === 'queued' || $st === 'running') {
        if ($format === 'html') {
            header('Content-Type: text/html; charset=utf-8');
            echo <<<HTML
            <div id="pending-turn" class="turn pending"
                 hx-get="api/status.php?id={$jobId}&format=html"
                 hx-trigger="every 1.2s"
                 hx-swap="outerHTML">
              <div class="breathing"></div>
            </div>
            HTML;
            exit;
        }
        ss_json_response(200, ['ok' => true, 'status' => $st]);
    }

    // Error
    if ($st === 'error') {
        if ($format === 'html') {
            $err = htmlspecialchars((string)($job['error_message'] ?? 'unknown error'), ENT_QUOTES);
            header('Content-Type: text/html; charset=utf-8');
            echo "<div class=\"turn error-turn\"><p class=\"error-msg\">{$err}</p></div>";
            exit;
        }
        ss_json_response(200, [
            'ok'    => true,
            'status' => 'error',
            'error' => $job['error_message'] ?? null,
        ]);
    }

    // Done — render only Claude's response.
    // Mono's message is already shown client-side by chat.js appendMonoMessage().
    if ($format === 'html') {
        $display = $job['display'] ?? [];
        $claudeActor = (string)($job['reply_actor'] ?? 'claude');
        $ts = $job['completed_at'] ?? $job['created_at'] ?? '';

        $claude = [
            'actor'   => $claudeActor,
            'display' => is_array($display) ? $display : [],
        ];

        header('Content-Type: text/html; charset=utf-8');
        $html = ss_render_claude_msg($claude, $ts);
        // If empty (secret/invisible), remove the pending element silently
        echo $html !== '' ? $html : '<span></span>';
        exit;
    }

    ss_json_response(200, [
        'ok'      => true,
        'status'  => 'done',
        'display' => $job['display'] ?? [],
        'actor'   => $job['reply_actor'] ?? 'claude',
    ]);
} catch (Throwable $e) {
    ss_json_response(500, ['ok' => false, 'error' => $e->getMessage()]);
}
