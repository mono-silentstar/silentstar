<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/jobs.php';
require_once __DIR__ . '/../lib/history.php';

try {
    ss_require_method('POST');
    ss_require_bridge_secret();
    ss_init_storage();

    $body = ss_read_json_body();
    $jobId = trim((string)($body['id'] ?? ''));
    if ($jobId === '') {
        ss_json_response(400, ['ok' => false, 'error' => 'missing_job_id']);
    }

    $status       = (string)($body['status'] ?? 'done');
    $replyText    = isset($body['reply_text']) ? (string)$body['reply_text'] : null;
    $display      = $body['display'] ?? [];
    $actor        = isset($body['actor']) ? (string)$body['actor'] : 'claude';
    $errorMessage = isset($body['error_message']) ? (string)$body['error_message'] : null;
    $turnId       = isset($body['turn_id']) ? (string)$body['turn_id'] : null;

    if (!is_array($display)) $display = [];

    $updated = ss_update_job($jobId, static function (array $row) use (
        $status, $replyText, $display, $actor, $errorMessage, $turnId
    ): array {
        $row['status']        = $status;
        $row['completed_at']  = ss_now_iso();
        $row['reply_text']    = $replyText;
        $row['display']       = $display;
        $row['reply_actor']   = $actor;
        $row['error_message'] = $errorMessage;
        $row['turn_id']       = $turnId;
        return $row;
    });

    if (!is_array($updated)) {
        ss_json_response(404, ['ok' => false, 'error' => 'job_not_found']);
    }

    // Append to conversation history if successful
    if ($status === 'done') {
        $historyEntry = [
            'job_id' => $jobId,
            'ts'     => ss_now_iso(),
            'mono'   => [
                'actor' => $updated['actor'] ?? 'mono',
                'text'  => $updated['message'] ?? '',
                'tags'  => $updated['tags'] ?? [],
                'image' => is_array($updated['upload'] ?? null)
                    ? ($updated['upload']['host_name'] ?? null)
                    : null,
            ],
            'claude' => [
                'actor'   => $actor,
                'display' => $display,
            ],
        ];
        ss_append_history($historyEntry);
    }

    // Clean up temp upload
    ss_delete_upload($updated);

    ss_json_response(200, ['ok' => true]);
} catch (Throwable $e) {
    ss_json_response(500, ['ok' => false, 'error' => $e->getMessage()]);
}
