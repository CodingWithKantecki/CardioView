// The heart: a real glTF model whose chambers contract by vertex displacement in a shader.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

export const CHAMBERS = ['ra', 'la', 'rv', 'lv'];
const GLOW = { ra: 0x5B9BFF, la: 0xFF5C83, rv: 0x5B9BFF, lv: 0xFF5C83 };
const STRENGTH = { ra: 0.08, la: 0.08, rv: 0.12, lv: 0.12 };
const OPACITY_STEPS = [1, 0.55, 0.25];

const VERTEX_HEAD = `
uniform vec3 uCenters[4];
uniform float uRadii[4];
uniform float uAct[4];
uniform float uStrength[4];
varying vec4 vChamber;
`;
const VERTEX_BODY = `
vec4 cardioW = vec4(0.0);
for (int i = 0; i < 4; i++) {
  float d = distance(position, uCenters[i]);
  float wi = 1.0 - smoothstep(0.0, uRadii[i], d);
  cardioW[i] = wi * uAct[i];
  transformed += (uCenters[i] - position) * wi * uStrength[i] * uAct[i];
}
vChamber = cardioW;
`;
const FRAGMENT_HEAD = `
uniform vec3 uGlow[4];
varying vec4 vChamber;
`;
const FRAGMENT_BODY = `
vec3 cardioGlow = vec3(0.0);
for (int i = 0; i < 4; i++) cardioGlow += uGlow[i] * vChamber[i];
gl_FragColor.rgb += cardioGlow * 0.18;
`;

export class Heart {
  constructor(container, { labels = {}, leaders = null, missing = null } = {}) {
    this.container = container;
    this.labels = labels;
    this.leaders = leaders;
    this.missingEl = missing;
    this.model = null;
    this.config = null;
    this.materials = [];
    this.meshes = [];
    this.state = { rotate: false, wireframe: false, opacityStep: 0, cutaway: false };

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.localClippingEnabled = true;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(30, 1, 0.01, 100);
    this.camera.position.set(0, 0.15, 4.2);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.enablePan = false;
    this.controls.minDistance = 1.5;
    this.controls.maxDistance = 9;
    this.controls.autoRotateSpeed = 1.5;

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(2, 3, 4);
    const rim = new THREE.DirectionalLight(0x5B9BFF, 0.8);
    rim.position.set(-3, 1, -3);
    this.scene.add(key, rim, new THREE.AmbientLight(0xffffff, 0.25));

    // shared uniforms (one set per chamber index: ra, la, rv, lv)
    this.uAct = { value: [0, 0, 0, 0] };
    this.uRadii = { value: [0.5, 0.5, 0.7, 0.7] };
    this.uStrength = { value: CHAMBERS.map((c) => STRENGTH[c]) };
    this.uGlow = { value: CHAMBERS.map((c) => new THREE.Color(GLOW[c])) };
    this.centersWorld = CHAMBERS.map(() => new THREE.Vector3());
    this.clipPlane = new THREE.Plane(new THREE.Vector3(0, 0, -1), 0.12);

    this.resize();
    new ResizeObserver(() => this.resize()).observe(container);
  }

  resize() {
    const w = Math.max(1, this.container.clientWidth);
    const h = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  async load(url = 'assets/heart/scene.gltf', configUrl = 'assets/heart.json') {
    try {
      const r = await fetch(configUrl, { cache: 'no-cache' });
      this.config = r.ok ? await r.json() : null;
    } catch { this.config = null; }
    let gltf;
    try {
      gltf = await new GLTFLoader().loadAsync(url);
    } catch (e) {
      console.warn('heart model not loaded:', e?.message || e);
      if (this.missingEl) this.missingEl.hidden = false;
      return false;
    }
    const root = gltf.scene;
    root.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(root);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const height = this.config?.height ?? 1.8;
    const s = height / Math.max(size.x, size.y, size.z);
    const holder = new THREE.Group();
    holder.add(root);
    root.position.sub(center);
    holder.scale.setScalar(s);
    if (this.config?.rotation) holder.rotation.set(...this.config.rotation.map((d) => (d * Math.PI) / 180));
    this.scene.add(holder);
    this.model = holder;
    holder.updateMatrixWorld(true);
    console.log('heart model bounding box (model units)', box.min.toArray(), box.max.toArray(), 'scale', s);

    root.traverse((obj) => {
      if (!obj.isMesh) return;
      this.meshes.push(obj);
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
      for (const mat of mats) this.patch(mat, obj);
    });
    this.applyConfig();
    for (const el of Object.values(this.labels)) el.hidden = false;
    if (this.missingEl) this.missingEl.hidden = true;
    return true;
  }

  patch(mat, mesh) {
    const uCenters = { value: CHAMBERS.map(() => new THREE.Vector3()) };
    mat.userData.uCenters = uCenters;
    mat.userData.mesh = mesh;
    mat.side = THREE.DoubleSide;
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.uCenters = uCenters;
      shader.uniforms.uRadii = this.uRadii;
      shader.uniforms.uAct = this.uAct;
      shader.uniforms.uStrength = this.uStrength;
      shader.uniforms.uGlow = this.uGlow;
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', '#include <common>\n' + VERTEX_HEAD)
        .replace('#include <begin_vertex>', '#include <begin_vertex>\n' + VERTEX_BODY);
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', '#include <common>\n' + FRAGMENT_HEAD)
        .replace('#include <dithering_fragment>', '#include <dithering_fragment>\n' + FRAGMENT_BODY);
    };
    mat.customProgramCacheKey = () => 'cardioview-chambers';
    mat.needsUpdate = true;
    this.materials.push(mat);
  }

  // Chamber centers come from heart.json in world space of the normalized model.
  applyConfig() {
    const cfg = this.config?.chambers || {};
    CHAMBERS.forEach((c, i) => {
      const ch = cfg[c] || {};
      this.centersWorld[i].fromArray(ch.center || [0, 0, 0]);
      this.uRadii.value[i] = ch.radius ?? this.uRadii.value[i];
    });
    for (const mat of this.materials) {
      const mesh = mat.userData.mesh;
      mesh.updateMatrixWorld(true);
      this.centersWorld.forEach((cw, i) => {
        mat.userData.uCenters.value[i].copy(cw);
        mesh.worldToLocal(mat.userData.uCenters.value[i]);
      });
    }
  }

  setActivation({ ra = 0, la = 0, rv = 0, lv = 0 }) {
    const v = this.uAct.value;
    v[0] = ra; v[1] = la; v[2] = rv; v[3] = lv;
  }

  setRotate(on) { this.state.rotate = on; this.controls.autoRotate = on; }

  setWireframe(on) {
    this.state.wireframe = on;
    for (const m of this.materials) m.wireframe = on;
  }

  cycleOpacity() {
    this.state.opacityStep = (this.state.opacityStep + 1) % OPACITY_STEPS.length;
    const o = OPACITY_STEPS[this.state.opacityStep];
    for (const m of this.materials) {
      m.transparent = o < 1;
      m.opacity = o;
      m.depthWrite = o >= 1;
      m.needsUpdate = true;
    }
    return o < 1;
  }

  setCutaway(on) {
    this.state.cutaway = on;
    for (const m of this.materials) {
      m.clippingPlanes = on ? [this.clipPlane] : [];
      m.needsUpdate = true;
    }
  }

  placeLabels() {
    if (!this.model) return;
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    const p = new THREE.Vector3();
    let svg = '';
    CHAMBERS.forEach((c, i) => {
      const el = this.labels[c];
      if (!el) return;
      p.copy(this.centersWorld[i]).project(this.camera);
      const ax = (p.x * 0.5 + 0.5) * w;
      const ay = (-p.y * 0.5 + 0.5) * h;
      const left = el.classList.contains('side-left');
      const lx = left ? w * 0.19 : w * 0.81;
      el.style.left = left ? `${Math.round(lx - el.offsetWidth)}px` : `${Math.round(lx)}px`;
      el.style.top = `${Math.round(ay - el.offsetHeight / 2)}px`;
      svg += `<line x1="${lx.toFixed(1)}" y1="${ay.toFixed(1)}" x2="${ax.toFixed(1)}" y2="${ay.toFixed(1)}"></line>`;
    });
    if (this.leaders) this.leaders.innerHTML = svg;
  }

  render() {
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.placeLabels();
  }
}
