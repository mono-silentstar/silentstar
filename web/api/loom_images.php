<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';

try {
    ss_require_login();

    $dir = ss_data_dir() . '/uploads_loom';
    ss_ensure_dir($dir);

    $method = strtoupper((string)($_SERVER['REQUEST_METHOD'] ?? 'GET'));

    // POST: actions (clear)
    if ($method === 'POST') {
        $action = trim((string)($_POST['action'] ?? ''));
        if ($action === 'clear') {
            $cleared = 0;
            $files = glob($dir . '/*');
            if (is_array($files)) {
                foreach ($files as $f) {
                    if (is_file($f)) {
                        @unlink($f);
                        $cleared++;
                    }
                }
            }
            ss_json_response(200, ['ok' => true, 'cleared' => $cleared]);
        }
        ss_json_response(400, ['ok' => false, 'error' => 'unknown_action']);
    }

    // GET with ?file= : serve a specific image
    $requestedFile = trim((string)($_GET['file'] ?? ''));
    if ($requestedFile !== '') {
        // Sanitize: only allow filename (no path traversal)
        $safe = basename($requestedFile);
        $path = $dir . '/' . $safe;

        if (!is_file($path)) {
            http_response_code(404);
            echo 'not found';
            exit;
        }

        $finfo = new finfo(FILEINFO_MIME_TYPE);
        $mime = (string)$finfo->file($path);
        if (!str_starts_with($mime, 'image/')) {
            http_response_code(403);
            echo 'not an image';
            exit;
        }

        header('Content-Type: ' . $mime);
        header('Content-Length: ' . filesize($path));
        header('Cache-Control: private, max-age=3600');
        readfile($path);
        exit;
    }

    // GET: list all uploaded images
    $files = glob($dir . '/*');
    $list = [];
    if (is_array($files)) {
        sort($files, SORT_STRING);
        $finfo = new finfo(FILEINFO_MIME_TYPE);
        foreach ($files as $f) {
            if (!is_file($f)) continue;
            $mime = (string)$finfo->file($f);
            if (!str_starts_with($mime, 'image/')) continue;
            $name = basename($f);
            clearstatcache(true, $f);
            $list[] = [
                'name' => $name,
                'size' => (int)filesize($f),
                'mime' => $mime,
                'uploaded_at' => date('c', (int)filemtime($f)),
            ];
        }
    }

    ss_json_response(200, [
        'ok'    => true,
        'count' => count($list),
        'files' => $list,
    ]);
} catch (Throwable $e) {
    ss_json_response(500, ['ok' => false, 'error' => $e->getMessage()]);
}
