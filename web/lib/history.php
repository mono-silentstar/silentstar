<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

/*
 * Conversation history — display-only log stored as JSONL.
 * Each line is a JSON object representing one exchange:
 *
 * {
 *   "job_id": "abc123",
 *   "ts": "2026-02-10T02:41:00+00:00",
 *   "mono": { "actor": "hasuki", "text": "...", "tags": ["plan"], "image": "filename.jpg" },
 *   "claude": { "actor": "claude", "display": [{"tag": "say", "content": "..."}] }
 * }
 *
 * Claude's display may be empty (all secret/processing). If so, no response renders.
 */

function ss_append_history(array $entry): void
{
    $path = ss_history_path();
    ss_ensure_dir(dirname($path));
    $line = json_encode($entry, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    file_put_contents($path, $line . "\n", FILE_APPEND | LOCK_EX);
}

function ss_read_history(int $limit = 50, int $offset = 0): array
{
    $path = ss_history_path();
    if (!is_file($path)) return [];

    $lines = file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    if (!is_array($lines) || count($lines) === 0) return [];

    // Most recent last — take from end
    $total = count($lines);
    $start = max(0, $total - $limit - $offset);
    $end = $total - $offset;
    if ($end <= 0) return [];

    $slice = array_slice($lines, $start, $end - $start);
    $entries = [];
    foreach ($slice as $line) {
        $decoded = json_decode($line, true);
        if (is_array($decoded)) $entries[] = $decoded;
    }
    return $entries;
}

function ss_history_count(): int
{
    $path = ss_history_path();
    if (!is_file($path)) return 0;
    $lines = file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    return is_array($lines) ? count($lines) : 0;
}

/* --- HTML rendering --- */

function ss_render_turn(array $entry): string
{
    $html = '';

    // Mono's message
    $mono = $entry['mono'] ?? null;
    if (is_array($mono)) {
        $html .= ss_render_mono_msg($mono, $entry['ts'] ?? '');
    }

    // Claude's response
    $claude = $entry['claude'] ?? null;
    if (is_array($claude)) {
        $display = $claude['display'] ?? [];
        if (is_array($display) && count($display) > 0) {
            $html .= ss_render_claude_msg($claude, $entry['ts'] ?? '');
        }
        // Empty display = invisible (secret). Nothing renders.
    }

    return $html;
}

function ss_render_mono_msg(array $mono, string $ts): string
{
    $actor = htmlspecialchars((string)($mono['actor'] ?? 'mono'), ENT_QUOTES);
    $text = htmlspecialchars((string)($mono['text'] ?? ''), ENT_QUOTES);
    $tags = $mono['tags'] ?? [];
    $image = $mono['image'] ?? null;
    $time = ss_format_time($ts);

    $tagPills = '';
    if (is_array($tags)) {
        foreach ($tags as $tag) {
            $t = htmlspecialchars((string)$tag, ENT_QUOTES);
            $tagPills .= "<span class=\"tag-pill\">{$t}</span>";
        }
    }

    $imageHtml = '';
    if (is_string($image) && $image !== '') {
        $safeName = htmlspecialchars($image, ENT_QUOTES);
        $imageHtml = "<div class=\"msg-image\"><img src=\"uploads/{$safeName}\" alt=\"\" loading=\"lazy\"></div>";
    }

    // Process text: convert inline tags to styled spans for display
    $bodyHtml = ss_render_mono_body($text);

    return <<<HTML
    <div class="turn">
      <div class="msg mono">
        <span class="actor" data-actor="{$actor}">{$actor}</span>
        {$imageHtml}
        <div class="body">{$bodyHtml}</div>
        <div class="msg-meta">{$tagPills}<time datetime="{$ts}">{$time}</time></div>
      </div>
    </div>
    HTML;
}

function ss_render_claude_msg(array $claude, string $ts): string
{
    $actor = htmlspecialchars((string)($claude['actor'] ?? 'claude'), ENT_QUOTES);
    $display = $claude['display'] ?? [];
    $time = ss_format_time($ts);

    $bodyHtml = '';
    if (is_array($display)) {
        foreach ($display as $span) {
            if (!is_array($span)) continue;
            $tag = (string)($span['tag'] ?? 'say');
            $content = htmlspecialchars((string)($span['content'] ?? ''), ENT_QUOTES);
            if ($content === '') continue;

            $class = match ($tag) {
                'do'      => 'display-do',
                'narrate' => 'display-narrate',
                default   => 'display-say',
            };
            $bodyHtml .= "<p class=\"{$class}\">{$content}</p>\n";
        }
    }

    if (trim($bodyHtml) === '') return '';

    return <<<HTML
    <div class="turn">
      <div class="msg claude">
        <span class="actor" data-actor="{$actor}">{$actor}</span>
        <div class="body">{$bodyHtml}</div>
        <div class="msg-meta"><time datetime="{$ts}">{$time}</time></div>
      </div>
    </div>
    HTML;
}

function ss_render_mono_body(string $text): string
{
    // Render inline tags in Mono's message for display
    // <plan>...</plan> → styled span, <pin>...</pin> → styled span
    // Everything else is plain text
    $text = preg_replace_callback(
        '/<(plan|pin)>(.*?)<\/\1>/s',
        static function (array $m): string {
            $tag = htmlspecialchars($m[1], ENT_QUOTES);
            $content = htmlspecialchars($m[2], ENT_QUOTES);
            return "<span class=\"inline-tag inline-{$tag}\">{$content}</span>";
        },
        $text
    );
    // Remaining text: escape any leftover HTML but preserve newlines
    // (the regex above already handled known tags)
    return nl2br((string)$text);
}

function ss_format_time(string $ts): string
{
    if ($ts === '') return '';
    $time = strtotime($ts);
    if ($time === false) return '';
    return date('g:i a', $time);
}
