<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';
require_once __DIR__ . '/../lib/history.php';

try {
    ss_require_method('GET');
    ss_require_login();

    $limit = max(1, min(200, (int)($_GET['limit'] ?? 50)));
    $offset = max(0, (int)($_GET['offset'] ?? 0));

    $result = ss_read_history($limit, $offset);
    $entries = $result['entries'];
    $total = $result['total'];

    header('Content-Type: text/html; charset=utf-8');

    if (count($entries) === 0) {
        echo '<div class="history-empty"></div>';
        exit;
    }

    $hasMore = ($offset + $limit) < $total;

    // Render load-more button if there's older history
    if ($hasMore) {
        $nextOffset = $offset + $limit;
        echo <<<HTML
        <div id="load-more" class="load-more"
             hx-get="api/history.php?limit={$limit}&offset={$nextOffset}"
             hx-trigger="click"
             hx-swap="outerHTML"
             hx-target="#load-more">
          <button class="load-more-btn">earlier</button>
        </div>
        HTML;
    }

    foreach ($entries as $entry) {
        echo ss_render_turn($entry);
    }
} catch (Throwable $e) {
    echo '<div class="error-msg">Failed to load history.</div>';
}
