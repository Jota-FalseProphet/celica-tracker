import * as THREE from "/three.module.js";

// Figuras cromadas 3D reales (WebGL). Si WebGL no está disponible: sin figuras.
const canvas = document.querySelector(".gl");
if (canvas) {
  try {
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    camera.position.z = 7;

    // el metal puro solo muestra reflejos: sin un entorno prefiltrado (PMREM) sale negro
    const pmrem = new THREE.PMREMGenerator(renderer);
    pmrem.compileEquirectangularShader();

    function skyTexture() {
      const dark = document.documentElement.dataset.theme === "dark";
      const c = document.createElement("canvas");
      c.width = 256; c.height = 256;
      const g = c.getContext("2d");
      const grad = g.createLinearGradient(0, 0, 0, 256);
      if (dark) {
        grad.addColorStop(0.00, "#13335a");
        grad.addColorStop(0.40, "#1d4e74");
        grad.addColorStop(0.49, "#bfe6ff");
        grad.addColorStop(0.53, "#16374f");
        grad.addColorStop(1.00, "#05101d");
      } else {
        grad.addColorStop(0.00, "#cfe9ff");
        grad.addColorStop(0.30, "#5ea3df");
        grad.addColorStop(0.46, "#ffffff");
        grad.addColorStop(0.52, "#1f4f6f");
        grad.addColorStop(0.72, "#123247");
        grad.addColorStop(1.00, "#0a2030");
      }
      g.fillStyle = grad;
      g.fillRect(0, 0, 256, 256);
      const tex = new THREE.CanvasTexture(c);
      tex.mapping = THREE.EquirectangularReflectionMapping;
      tex.colorSpace = THREE.SRGBColorSpace;
      return tex;
    }
    function makeEnv() {
      const t = skyTexture();
      const env = pmrem.fromEquirectangular(t).texture;
      t.dispose();
      return env;
    }
    scene.environment = makeEnv();

    scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const key = new THREE.DirectionalLight(0xffffff, 1.2);
    key.position.set(3, 5, 4);
    scene.add(key);

    const chrome = () => new THREE.MeshPhysicalMaterial({
      color: 0xeaf1f6,
      metalness: 1,
      roughness: 0.03,
      iridescence: 0.4,
      iridescenceIOR: 1.3,
      envMapIntensity: 1.6,
      clearcoat: 0.25,
      clearcoatRoughness: 0.18,
    });

    const torus = new THREE.Mesh(new THREE.TorusGeometry(1.15, 0.42, 64, 140), chrome());
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(1.05, 80, 80), chrome());
    const knot = new THREE.Mesh(new THREE.TorusKnotGeometry(0.52, 0.2, 160, 24), chrome());
    const group = new THREE.Group();
    group.add(torus, sphere, knot);
    scene.add(group);

    const P = {
      torus:  { m: torus,  x: 0, y0: 1.5,  bob: 0.18, ph: 0, z: 0 },
      sphere: { m: sphere, x: 0, y0: -0.7, bob: 0.16, ph: 1, z: -0.5 },
      knot:   { m: knot,   x: 0, y0: -1.9, bob: 0.14, ph: 2, z: -1 },
    };

    // móvil: columna vertical pequeña; PC: pegadas a los lados, fuera del texto
    function layout() {
      const vH = Math.tan(camera.fov * Math.PI / 360) * camera.position.z;
      const vW = vH * camera.aspect;
      const mobile = camera.aspect < 0.9;
      const s = mobile ? 0.5 : 1;
      torus.scale.setScalar(s); sphere.scale.setScalar(s); knot.scale.setScalar(s);
      if (mobile) {
        P.torus.x = 0.35;  P.torus.y0 = 1.95;
        P.sphere.x = -0.3; P.sphere.y0 = 0.1;
        P.knot.x = 0.3;    P.knot.y0 = -1.85;
      } else {
        const ex = Math.min(vW * 0.92, 3.8);
        P.torus.x = ex;       P.torus.y0 = 1.5;
        P.sphere.x = -ex;     P.sphere.y0 = -0.7;
        P.knot.x = ex * 0.92; P.knot.y0 = -1.9;
      }
    }

    function resize() {
      renderer.setSize(window.innerWidth, window.innerHeight, false);
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      layout();
    }
    resize();
    addEventListener("resize", resize, { passive: true });

    let px = 0, py = 0;
    if (!reduce && matchMedia("(pointer: fine)").matches) {
      addEventListener("pointermove", e => {
        px = e.clientX / window.innerWidth - 0.5;
        py = e.clientY / window.innerHeight - 0.5;
      }, { passive: true });
    }

    let first = true;
    function render(t) {
      torus.rotation.set(0.5 + t * 1.1, t * 1.3, 0);
      sphere.rotation.y = t * 0.9;
      knot.rotation.set(t * 1.4, t * 1.1, 0);
      for (const k in P) {
        const p = P[k];
        p.m.position.set(p.x, p.y0 + Math.sin(t * 1.8 + p.ph) * p.bob, p.z);
      }
      scene.rotation.y += (px * 0.28 - scene.rotation.y) * 0.06;
      scene.rotation.x += (py * 0.2 - scene.rotation.x) * 0.06;
      renderer.render(scene, camera);
      if (first) { first = false; canvas.classList.add("ready"); }
    }

    if (reduce) {
      render(0);
    } else {
      const loop = t => { render(t * 0.0004); requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
    }

    // al cambiar de tema, regenerar el entorno reflejado
    const tg = document.querySelector("#theme-btn");
    if (tg) tg.addEventListener("click", () => setTimeout(() => {
      const old = scene.environment;
      scene.environment = makeEnv();
      if (old) old.dispose();
      if (reduce) render(0);
    }, 80));

  } catch (err) {
    // sin WebGL: simplemente no se muestran figuras
  }
}
