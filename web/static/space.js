/*
 * space.js — the ambient background
 *
 * Slow-drifting particles in warm darkness. A gradient that breathes.
 * This is the room we sit in.
 */

(function () {
  const canvas = document.getElementById('space-canvas');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  let w, h;
  let mouse = { x: -1, y: -1 };
  let time = 0;

  // --- Particles ---

  const PARTICLE_COUNT = 60;
  const particles = [];

  class Particle {
    constructor() {
      this.reset(true);
    }

    reset(initial = false) {
      this.x = Math.random() * (w || window.innerWidth);
      this.y = Math.random() * (h || window.innerHeight);
      this.size = 0.5 + Math.random() * 2;
      this.baseAlpha = 0.04 + Math.random() * 0.14;
      this.alpha = this.baseAlpha;
      this.vx = (Math.random() - 0.5) * 0.15;
      this.vy = (Math.random() - 0.5) * 0.1 - 0.02; // slight upward drift
      this.phase = Math.random() * Math.PI * 2;
      this.twinkleSpeed = 0.005 + Math.random() * 0.015;
      // Warm whites, faint ambers, occasional cool
      const roll = Math.random();
      if (roll < 0.6) {
        this.color = { r: 210 + Math.random() * 30, g: 200 + Math.random() * 20, b: 185 + Math.random() * 20 };
      } else if (roll < 0.85) {
        this.color = { r: 196, g: 168, b: 130 }; // amber
      } else {
        this.color = { r: 139, g: 142, b: 200 }; // dusty blue
      }
    }

    update() {
      // Drift
      this.x += this.vx + Math.sin(time * 0.0003 + this.phase) * 0.08;
      this.y += this.vy + Math.cos(time * 0.0002 + this.phase) * 0.04;

      // Twinkle
      this.alpha = this.baseAlpha * (0.5 + 0.5 * Math.sin(time * this.twinkleSpeed + this.phase));

      // Subtle mouse parallax
      if (mouse.x >= 0) {
        const dx = (mouse.x - w / 2) / w;
        const dy = (mouse.y - h / 2) / h;
        this.x += dx * 0.05 * this.size;
        this.y += dy * 0.03 * this.size;
      }

      // Wrap edges
      if (this.x < -10) this.x = w + 10;
      if (this.x > w + 10) this.x = -10;
      if (this.y < -10) this.y = h + 10;
      if (this.y > h + 10) this.y = -10;
    }

    draw() {
      const { r, g, b } = this.color;
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${r|0}, ${g|0}, ${b|0}, ${this.alpha})`;
      ctx.fill();

      // Glow for larger particles
      if (this.size > 1.2) {
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.size * 3, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${r|0}, ${g|0}, ${b|0}, ${this.alpha * 0.15})`;
        ctx.fill();
      }
    }
  }

  // --- Gradient ---

  function drawGradient() {
    // Slowly shifting warm gradient
    const cycle = time * 0.00004;
    const r1 = 14 + Math.sin(cycle) * 3;
    const g1 = 13 + Math.sin(cycle + 1) * 2;
    const b1 = 18 + Math.sin(cycle + 2) * 4;

    const r2 = 10 + Math.sin(cycle + 3) * 2;
    const g2 = 10 + Math.cos(cycle + 1) * 2;
    const b2 = 14 + Math.sin(cycle + 4) * 3;

    const grad = ctx.createRadialGradient(w * 0.5, h * 0.4, 0, w * 0.5, h * 0.4, Math.max(w, h) * 0.8);
    grad.addColorStop(0, `rgb(${r1|0}, ${g1|0}, ${b1|0})`);
    grad.addColorStop(1, `rgb(${r2|0}, ${g2|0}, ${b2|0})`);

    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);
  }

  // --- Noise texture (very subtle, pre-rendered to offscreen canvas) ---

  let noiseCanvas = null;

  function generateNoise() {
    noiseCanvas = document.createElement('canvas');
    // Cap noise resolution to save memory on high-res displays
    const maxDim = 512;
    const noiseW = Math.min(w, maxDim);
    const noiseH = Math.min(h, maxDim);
    noiseCanvas.width = noiseW;
    noiseCanvas.height = noiseH;
    const nctx = noiseCanvas.getContext('2d');
    const imageData = nctx.createImageData(noiseW, noiseH);
    const data = imageData.data;
    for (let i = 0; i < data.length; i += 4) {
      const v = Math.random() * 12;
      data[i] = v;
      data[i + 1] = v;
      data[i + 2] = v;
      data[i + 3] = 8;
    }
    nctx.putImageData(imageData, 0, 0);
  }

  // --- Main loop ---

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = window.innerWidth;
    h = window.innerHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    generateNoise();
  }

  function init() {
    resize();
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      particles.push(new Particle());
    }
  }

  function frame(ts) {
    time = ts;

    // Background gradient
    drawGradient();

    // Noise overlay (drawn via drawImage to respect DPR transform)
    if (noiseCanvas) {
      ctx.globalAlpha = 0.4;
      ctx.drawImage(noiseCanvas, 0, 0, w, h);
      ctx.globalAlpha = 1.0;
    }

    // Particles
    for (const p of particles) {
      p.update();
      p.draw();
    }

    requestAnimationFrame(frame);
  }

  // --- Events ---

  window.addEventListener('resize', () => {
    resize();
    // Redistribute particles
    for (const p of particles) {
      if (p.x > w || p.y > h) p.reset();
    }
  });

  document.addEventListener('mousemove', (e) => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
  });

  document.addEventListener('touchmove', (e) => {
    if (e.touches.length > 0) {
      mouse.x = e.touches[0].clientX;
      mouse.y = e.touches[0].clientY;
    }
  }, { passive: true });

  document.addEventListener('touchend', () => {
    mouse.x = -1;
    mouse.y = -1;
  });

  document.addEventListener('mouseleave', () => {
    mouse.x = -1;
    mouse.y = -1;
  });

  // --- Go ---

  init();
  requestAnimationFrame(frame);
})();
