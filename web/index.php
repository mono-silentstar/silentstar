<?php
declare(strict_types=1);

require_once __DIR__ . '/lib/auth.php';

ss_session_start();
$loggedIn = ss_is_logged_in();
$authConfigured = ss_auth_configured();
$loginError = isset($_GET['login_error']) && $_GET['login_error'] === '1';
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0e0e12">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <title>silentstar</title>
  <link rel="manifest" href="manifest.json">
  <link rel="icon" href="static/icon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="static/icon-192.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="static/style.css?v=6">
</head>
<body>

<canvas id="space-canvas"></canvas>

<?php if (!$loggedIn): ?>

  <div class="login-shell">
    <div class="login-form">
      <div class="login-title">silentstar</div>
      <?php if (!$authConfigured): ?>
        <p class="login-error">password not configured</p>
      <?php elseif ($loginError): ?>
        <p class="login-error">wrong password</p>
      <?php endif; ?>
      <form method="post" action="api/login.php">
        <input class="login-input" type="password" name="password"
               placeholder="..." required autocomplete="current-password"
               <?= $authConfigured ? '' : 'disabled' ?>>
        <button class="login-submit" type="submit" <?= $authConfigured ? '' : 'disabled' ?>>enter</button>
      </form>
    </div>
  </div>

<?php else: ?>

  <div class="shell">

    <!-- Header -->
    <div class="header">
      <div class="header-left">
        <span class="site-name">silentstar</span>
        <div class="bridge-status">
          <span id="bridge-dot" class="bridge-dot"></span>
          <span id="bridge-label">...</span>
        </div>
      </div>
      <div class="header-right">
        <button type="button" id="loom-upload-btn" class="loom-upload-btn" title="upload for loom">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
            <circle cx="12" cy="13" r="4"/>
          </svg>
          <span id="loom-badge" class="loom-badge"></span>
        </button>
        <input type="file" id="loom-input" accept="image/*" multiple>
        <form method="post" action="api/logout.php">
          <button class="logout-btn" type="submit">leave</button>
        </form>
      </div>
    </div>

    <!-- Chat -->
    <div id="chat-area" class="chat-area">
      <div id="chat-log"
           hx-get="api/history.php"
           hx-trigger="load"
           hx-swap="innerHTML">
      </div>
    </div>

    <!-- Input -->
    <div class="input-area">

      <div class="identity-row">
        <span class="identity-chip" data-identity="hasuki" role="button" aria-pressed="false">hasuki</span>
        <span class="identity-chip" data-identity="renki" role="button" aria-pressed="false">renki</span>
        <span class="identity-chip" data-identity="luna" role="button" aria-pressed="false">luna</span>
        <span class="identity-chip" data-identity="chloe" role="button" aria-pressed="false">chloe</span>
        <span class="identity-chip" data-identity="strah" role="button" aria-pressed="false">strah</span>
      </div>

      <form id="chat-form" enctype="multipart/form-data">
        <div class="input-row">
          <div class="input-wrap">
            <div id="msg-input" class="msg-input" contenteditable="true"
                 role="textbox" aria-multiline="true" aria-label="Message"></div>
          </div>
        </div>

        <div id="image-preview" class="image-preview">
          <img id="preview-img" src="" alt="">
          <button type="button" id="remove-image" class="remove-image">&times;</button>
        </div>

        <input type="file" id="image-input" accept="image/*">

        <div class="actions-row">
          <button type="button" class="tag-toggle" data-tag="do" aria-pressed="false">do</button>
          <button type="button" class="tag-toggle" data-tag="narrate" aria-pressed="false">narrate</button>
          <span class="tag-sep"></span>
          <button type="button" class="tag-toggle" data-tag="plan" aria-pressed="false">plan</button>
          <button type="button" class="tag-toggle" data-tag="pin" aria-pressed="false">pin</button>
          <button type="button" id="image-btn" class="image-btn" title="attach image">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
              <circle cx="8.5" cy="8.5" r="1.5"/>
              <polyline points="21 15 16 10 5 21"/>
            </svg>
          </button>
          <span class="spacer"></span>
          <button type="submit" id="send-btn" class="send-btn">send</button>
        </div>
      </form>

    </div>

  </div>

  <script src="https://unpkg.com/htmx.org@2.0.4" crossorigin="anonymous"></script>
  <script src="static/space.js?v=6"></script>
  <script src="static/chat.js?v=6"></script>

<?php endif; ?>

<script>
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}
</script>
</body>
</html>
