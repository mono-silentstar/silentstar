<?php
declare(strict_types=1);

require_once __DIR__ . '/db.php';

function mono_allowed_identity_tags(): array
{
    return [
        'mono',
        'hasuki',
        'renki',
        'luna',
        'chloe',
        'strah',
        'claude',
        "y'lhara",
    ];
}

function mono_allowed_event_tags(): array
{
    return [
        'plan',
        'secret',
        'say',
        'rp',
        'nr',
    ];
}

function mono_normalize_actor(?string $actor, string $fallback): string
{
    $candidate = strtolower(trim((string)$actor));
    if ($candidate === '') {
        return $fallback;
    }
    if (preg_match("/^[a-z0-9_'-]{1,64}$/", $candidate) !== 1) {
        return $fallback;
    }
    if (!in_array($candidate, mono_allowed_identity_tags(), true)) {
        return $fallback;
    }
    return $candidate;
}

function mono_tag_tokens_from_input(mixed $input): array
{
    if (is_array($input)) {
        $all = [];
        foreach ($input as $entry) {
            $all = array_merge($all, mono_tag_tokens_from_input($entry));
        }
        return $all;
    }

    if ($input === null) {
        return [];
    }
    if (!is_scalar($input)) {
        return [];
    }

    $parts = preg_split('/[\s,;|]+/', trim((string)$input));
    if (!is_array($parts)) {
        return [];
    }
    return $parts;
}

function mono_merge_tag_inputs(mixed ...$inputs): array
{
    $allowed = array_flip(mono_allowed_event_tags());
    $tags = [];
    foreach ($inputs as $input) {
        foreach (mono_tag_tokens_from_input($input) as $rawTag) {
            $tag = strtolower(trim($rawTag));
            if ($tag === '') {
                continue;
            }
            if (preg_match('/^[a-z0-9_-]{1,32}$/', $tag) !== 1) {
                continue;
            }
            if (!isset($allowed[$tag])) {
                continue;
            }
            $tags[$tag] = true;
        }
    }
    return array_keys($tags);
}

function mono_message_has_time_language(string $text): bool
{
    return preg_match(
        '/\b(' .
        'today|tonight|tomorrow|tmr|yesterday|next|this\s+(?:week|month|year)|' .
        'monday|tuesday|wednesday|thursday|friday|saturday|sunday|' .
        'in\s+\d+\s*(?:m|min|mins|minute|minutes|h|hr|hrs|hour|hours|day|days|week|weeks|month|months|year|years)|' .
        '\d{1,2}:\d{2}\s*(?:am|pm)?|' .
        '\d{1,2}\s*(?:am|pm)|' .
        '\d{4}-\d{1,2}-\d{1,2}|' .
        '\d{1,2}\/\d{1,2}(?:\/\d{2,4})?' .
        ')\b/i',
        $text
    ) === 1;
}

function mono_parse_plan_due(string $content, ?DateTimeImmutable $now = null): ?string
{
    $raw = trim($content);
    if ($raw === '') {
        return null;
    }

    $nowUtc = $now ?? new DateTimeImmutable('now', new DateTimeZone('UTC'));
    $lower = strtolower($raw);

    if (preg_match('/\b(daily|every day)\b/', $lower) === 1) {
        return $nowUtc->modify('+1 day')->format(DateTimeInterface::ATOM);
    }
    if (preg_match('/\b(weekly|every week)\b/', $lower) === 1) {
        return $nowUtc->modify('+1 week')->format(DateTimeInterface::ATOM);
    }
    if (preg_match('/\b(monthly|every month)\b/', $lower) === 1) {
        return $nowUtc->modify('+1 month')->format(DateTimeInterface::ATOM);
    }

    if (!mono_message_has_time_language($raw)) {
        return null;
    }

    $parsedTs = strtotime($raw, $nowUtc->getTimestamp());
    if ($parsedTs === false) {
        return null;
    }

    $due = (new DateTimeImmutable('@' . (string)$parsedTs))->setTimezone(new DateTimeZone('UTC'));

    $hasDayName = preg_match('/\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/', $lower) === 1;
    $hasPastDirection = preg_match('/\b(last|ago|yesterday)\b/', $lower) === 1;
    $hasExplicitDate = preg_match(
        '/\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[\/-]\d{1,2}(?:[\/-]\d{2,4})?\b/',
        $lower
    ) === 1;

    if ($hasDayName && !$hasPastDirection && !$hasExplicitDate && $due <= $nowUtc) {
        $due = $due->modify('+7 days');
    }

    return $due->format(DateTimeInterface::ATOM);
}

function mono_archive_uploaded_image(string $sourcePath, string $originalName): string
{
    if (!is_file($sourcePath)) {
        throw new RuntimeException('image source path missing for archive');
    }

    $archiveDir = mono_image_archive_dir();
    mono_ensure_dir($archiveDir);

    $safeName = mono_normalize_filename($originalName);
    $targetName = gmdate('Ymd_His') . '__' . mono_random_id(6) . '__' . $safeName;
    $targetPath = $archiveDir . '/' . $targetName;

    if (!copy($sourcePath, $targetPath)) {
        throw new RuntimeException('failed to archive uploaded image');
    }
    @chmod($targetPath, 0600);

    return $targetPath;
}

function mono_ingest_event(array $payload): array
{
    $content = array_key_exists('content', $payload) ? (string)$payload['content'] : '';
    $fallbackActor = strtolower(trim((string)($payload['fallback_actor'] ?? '')));
    if ($fallbackActor === '') {
        throw new RuntimeException('fallback_actor is required for ingestion');
    }

    $actor = mono_normalize_actor(
        array_key_exists('actor', $payload) ? (string)$payload['actor'] : null,
        $fallbackActor
    );
    $imagePath = array_key_exists('image_path', $payload) ? trim((string)$payload['image_path']) : '';
    $imagePath = $imagePath !== '' ? $imagePath : null;

    $tags = mono_merge_tag_inputs(
        $payload['tags'] ?? null,
        $payload['content_tags'] ?? null,
        $payload['display_tags'] ?? null
    );

    $createPlan = (bool)($payload['create_plan_from_tag'] ?? true);
    $incrementTurn = (bool)($payload['increment_turn'] ?? false);
    $nowIso = mono_now_iso();

    $pdo = mono_memory_db();
    $ownsTx = !$pdo->inTransaction();
    if ($ownsTx) {
        $pdo->beginTransaction();
    }

    try {
        $insertEvent = $pdo->prepare(
            "INSERT INTO events (ts, content, actor, image_path) VALUES (:ts, :content, :actor, :image_path)"
        );
        $insertEvent->execute([
            ':ts' => $nowIso,
            ':content' => $content,
            ':actor' => $actor,
            ':image_path' => $imagePath,
        ]);

        $eventId = (int)$pdo->lastInsertId();

        if ($tags !== []) {
            $insertTag = $pdo->prepare(
                "INSERT OR IGNORE INTO event_tags (event_id, tag) VALUES (:event_id, :tag)"
            );
            foreach ($tags as $tag) {
                $insertTag->execute([
                    ':event_id' => $eventId,
                    ':tag' => $tag,
                ]);
            }
        }

        $planId = null;
        $due = null;
        if ($createPlan && in_array('plan', $tags, true)) {
            $due = mono_parse_plan_due($content);
            $insertPlan = $pdo->prepare(
                <<<SQL
                INSERT INTO plans (event_id, actor, summary, due, status, created_at)
                VALUES (:event_id, :actor, :summary, :due, 'active', :created_at)
                SQL
            );
            $insertPlan->execute([
                ':event_id' => $eventId,
                ':actor' => $actor,
                ':summary' => $content,
                ':due' => $due,
                ':created_at' => $nowIso,
            ]);
            $planId = (int)$pdo->lastInsertId();
        }

        $turn = null;
        if ($incrementTurn) {
            $turn = mono_state_increment_turn($pdo);
        }

        if ($ownsTx && $pdo->inTransaction()) {
            $pdo->commit();
        }

        return [
            'event_id' => $eventId,
            'actor' => $actor,
            'tags' => $tags,
            'plan_id' => $planId,
            'due' => $due,
            'turn' => $turn,
            'ts' => $nowIso,
        ];
    } catch (Throwable $e) {
        if ($ownsTx && $pdo->inTransaction()) {
            $pdo->rollBack();
        }
        throw $e;
    }
}
