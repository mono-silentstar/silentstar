<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function mono_memory_db_path(): string
{
    $configured = trim((string)mono_cfg('memory_db_path', ''));
    if ($configured === '') {
        return mono_data_dir() . '/memory.sqlite';
    }
    return mono_resolve_repo_path($configured);
}

function mono_image_archive_dir(): string
{
    $configured = trim((string)mono_cfg('image_archive_dir', ''));
    $path = $configured !== '' ? $configured : (mono_data_dir() . '/img-dump');
    $path = mono_resolve_repo_path($path);
    return rtrim($path, "/\\");
}

function mono_memory_db(): PDO
{
    static $pdo = null;
    if ($pdo instanceof PDO) {
        return $pdo;
    }

    mono_ensure_dir(dirname(mono_memory_db_path()));
    mono_ensure_dir(mono_image_archive_dir());

    $pdo = new PDO('sqlite:' . mono_memory_db_path(), null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);

    $pdo->exec('PRAGMA foreign_keys = ON');
    $pdo->exec('PRAGMA busy_timeout = 5000');
    try {
        $pdo->exec('PRAGMA journal_mode = WAL');
    } catch (Throwable) {
        // Keep default journal mode if WAL is unavailable on this filesystem.
    }

    mono_memory_migrate($pdo);

    return $pdo;
}

function mono_memory_migrate(PDO $pdo): void
{
    $stmts = [
        <<<SQL
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            content TEXT NOT NULL,
            actor TEXT,
            image_path TEXT
        )
        SQL,
        "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC)",
        <<<SQL
        CREATE TABLE IF NOT EXISTS event_tags (
            event_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            PRIMARY KEY (event_id, tag),
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        )
        SQL,
        "CREATE INDEX IF NOT EXISTS idx_event_tags_tag ON event_tags(tag)",
        <<<SQL
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            actor TEXT,
            summary TEXT NOT NULL,
            due TEXT,
            status TEXT NOT NULL CHECK (status IN ('active', 'done', 'cancelled', 'expired')),
            created_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        )
        SQL,
        "CREATE INDEX IF NOT EXISTS idx_plans_status_due ON plans(status, due)",
        <<<SQL
        CREATE TABLE IF NOT EXISTS fragments (
            key TEXT PRIMARY KEY,
            ambient TEXT,
            recognition TEXT,
            inventory TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        SQL,
        <<<SQL
        CREATE TABLE IF NOT EXISTS fragment_sources (
            fragment_key TEXT NOT NULL,
            event_id INTEGER NOT NULL,
            PRIMARY KEY (fragment_key, event_id),
            FOREIGN KEY (fragment_key) REFERENCES fragments(key) ON DELETE CASCADE,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        )
        SQL,
        <<<SQL
        CREATE TABLE IF NOT EXISTS fragment_edges (
            source_key TEXT NOT NULL,
            target_key TEXT NOT NULL,
            relation TEXT,
            PRIMARY KEY (source_key, target_key),
            FOREIGN KEY (source_key) REFERENCES fragments(key) ON DELETE CASCADE,
            FOREIGN KEY (target_key) REFERENCES fragments(key) ON DELETE CASCADE
        )
        SQL,
        "CREATE INDEX IF NOT EXISTS idx_fragment_edges_source ON fragment_edges(source_key)",
        "CREATE INDEX IF NOT EXISTS idx_fragment_edges_target ON fragment_edges(target_key)",
        <<<SQL
        CREATE TABLE IF NOT EXISTS maintenance_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            run_type TEXT NOT NULL CHECK (run_type IN ('weekly', 'monthly', 'manual', 'bootstrap'))
        )
        SQL,
        <<<SQL
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        SQL,
    ];

    foreach ($stmts as $sql) {
        $pdo->exec($sql);
    }
}

function mono_state_get(PDO $pdo, string $key): ?string
{
    $stmt = $pdo->prepare("SELECT value FROM state WHERE key = :key LIMIT 1");
    $stmt->execute([':key' => $key]);
    $value = $stmt->fetchColumn();
    return is_string($value) ? $value : null;
}

function mono_state_set(PDO $pdo, string $key, string $value): void
{
    $stmt = $pdo->prepare(
        <<<SQL
        INSERT INTO state (key, value, updated_at)
        VALUES (:key, :value, :updated_at)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        SQL
    );
    $stmt->execute([
        ':key' => $key,
        ':value' => $value,
        ':updated_at' => mono_now_iso(),
    ]);
}

function mono_state_increment_turn(PDO $pdo): int
{
    $ownsTx = !$pdo->inTransaction();
    if ($ownsTx) {
        $pdo->beginTransaction();
    }

    try {
        $currentRaw = mono_state_get($pdo, 'current_turn');
        $current = is_string($currentRaw) ? (int)$currentRaw : 0;
        if ($current < 0) {
            $current = 0;
        }

        $next = $current + 1;
        mono_state_set($pdo, 'current_turn', (string)$next);

        if ($ownsTx && $pdo->inTransaction()) {
            $pdo->commit();
        }
        return $next;
    } catch (Throwable $e) {
        if ($ownsTx && $pdo->inTransaction()) {
            $pdo->rollBack();
        }
        throw $e;
    }
}
