<?php
declare(strict_types=1);

return [
    // Generate with: php -r 'echo password_hash("your-password", PASSWORD_DEFAULT), PHP_EOL;'
    'app_password_hash' => '$2y$10$replace_with_real_hash',
    // Generate with: openssl rand -hex 32
    'bridge_shared_secret' => 'replace_with_long_random_secret',
    'bridge_online_ttl_sec' => 8,
    'job_stale_sec' => 300,
    'timezone' => 'UTC',
    'data_dir' => 'data',
    'memory_db_path' => 'data/memory.sqlite',
    'image_archive_dir' => 'data/img-dump',
];
