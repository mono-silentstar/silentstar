<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';

/**
 * SSE streaming endpoint — tails a .stream file and sends chunks as events.
 *
 * GET /api/stream.php?id={jobId}
 *
 * Events:
 *   event: chunk\ndata: {"t": "text"}\n\n
 *   event: done\ndata: {}\n\n
 *
 * Falls back gracefully if stream file doesn't exist (job already complete).
 */
try {
    ss_require_method('GET');
    ss_require_login();

    $jobId = trim((string)($_GET['id'] ?? ''));
    if ($jobId === '' || preg_match('/^[a-f0-9]{16,64}$/', $jobId) !== 1) {
        ss_json_response(400, ['ok' => false, 'error' => 'invalid_job_id']);
    }

    $streamPath = ss_state_dir() . '/' . $jobId . '.stream';

    // If no stream file, job may already be complete — send redirect hint
    if (!file_exists($streamPath)) {
        $job = ss_get_job($jobId);
        if (is_array($job) && ($job['status'] ?? '') === 'done') {
            // Job already done, client should use status.php
            header('Content-Type: text/event-stream');
            header('Cache-Control: no-cache');
            header('X-Accel-Buffering: no');
            echo "event: fallback\ndata: {\"status\":\"done\"}\n\n";
            flush();
            exit;
        }
        // Job not found or still queued — wait briefly for stream file
        usleep(500000); // 500ms
        if (!file_exists($streamPath)) {
            header('Content-Type: text/event-stream');
            header('Cache-Control: no-cache');
            header('X-Accel-Buffering: no');
            echo "event: fallback\ndata: {\"status\":\"pending\"}\n\n";
            flush();
            exit;
        }
    }

    // SSE headers
    header('Content-Type: text/event-stream');
    header('Cache-Control: no-cache');
    header('Connection: keep-alive');
    header('X-Accel-Buffering: no');

    // Disable output buffering
    while (ob_get_level()) ob_end_flush();

    set_time_limit(120);

    $fh = fopen($streamPath, 'r');
    if ($fh === false) {
        echo "event: error\ndata: {\"error\":\"cannot_open_stream\"}\n\n";
        flush();
        exit;
    }

    $startTime = time();
    $maxSeconds = 110; // slightly under set_time_limit

    while (true) {
        // Timeout check
        if ((time() - $startTime) > $maxSeconds) {
            echo "event: timeout\ndata: {}\n\n";
            flush();
            break;
        }

        // Check client disconnect
        if (connection_aborted()) {
            break;
        }

        $line = fgets($fh);
        if ($line !== false) {
            $line = trim($line);
            if ($line === '') continue;

            $data = json_decode($line, true);
            if (!is_array($data)) continue;

            if (isset($data['done'])) {
                echo "event: done\ndata: {}\n\n";
                flush();
                break;
            }

            if (isset($data['t'])) {
                $encoded = json_encode($data, JSON_UNESCAPED_UNICODE);
                echo "event: chunk\ndata: " . $encoded . "\n\n";
                flush();
            }
        } else {
            // No new data — poll
            clearstatcache(true, $streamPath);
            usleep(50000); // 50ms
        }
    }

    fclose($fh);
} catch (Throwable $e) {
    if (isset($fh) && is_resource($fh)) fclose($fh);
    // Try to send error as SSE if headers already sent
    if (headers_sent()) {
        echo "event: error\ndata: " . json_encode(['error' => $e->getMessage()]) . "\n\n";
        flush();
    } else {
        ss_json_response(500, ['ok' => false, 'error' => $e->getMessage()]);
    }
}
