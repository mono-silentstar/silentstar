<?php
declare(strict_types=1);

require_once __DIR__ . '/../lib/auth.php';

try {
    ss_require_method('POST');
    ss_require_login();

    $dir = ss_data_dir() . '/uploads_loom';
    ss_ensure_dir($dir);

    // Handle both single and multiple file uploads
    $files = $_FILES['images'] ?? null;
    if (!$files || !is_array($files['name'])) {
        ss_json_response(400, ['ok' => false, 'error' => 'no_files']);
    }

    // Normalize to array of files (PHP multi-upload structure)
    $names    = is_array($files['name'])     ? $files['name']     : [$files['name']];
    $tmpNames = is_array($files['tmp_name']) ? $files['tmp_name'] : [$files['tmp_name']];
    $errors   = is_array($files['error'])    ? $files['error']    : [$files['error']];

    $uploaded = [];
    $finfo = new finfo(FILEINFO_MIME_TYPE);

    for ($i = 0, $count = count($names); $i < $count; $i++) {
        if ((int)$errors[$i] !== UPLOAD_ERR_OK) continue;

        $tmpName = (string)$tmpNames[$i];
        if ($tmpName === '' || !is_uploaded_file($tmpName)) continue;

        $mime = (string)$finfo->file($tmpName);
        if (!str_starts_with($mime, 'image/')) continue;

        $origName = ss_normalize_filename((string)$names[$i]);
        $ts = date('Ymd-His');
        $hostName = $ts . '_' . $origName;
        $hostPath = $dir . '/' . $hostName;

        if (move_uploaded_file($tmpName, $hostPath)) {
            @chmod($hostPath, 0644);
            clearstatcache(true, $hostPath);
            $uploaded[] = [
                'name' => $hostName,
                'size' => (int)filesize($hostPath),
                'mime' => $mime,
            ];
        }
    }

    if (count($uploaded) === 0) {
        ss_json_response(400, ['ok' => false, 'error' => 'no_valid_images']);
    }

    ss_json_response(200, [
        'ok'    => true,
        'count' => count($uploaded),
        'files' => $uploaded,
    ]);
} catch (Throwable $e) {
    ss_json_response(500, ['ok' => false, 'error' => $e->getMessage()]);
}
