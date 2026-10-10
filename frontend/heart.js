// The heart: a real glTF model whose chambers contract by vertex displacement in a shader.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

export const CHAMBERS = ['ra', 'la', 'rv', 'lv'];
const GLOW = { ra: 0x5B9BFF, la: 0xFF5C83, rv: 0x5B9BFF, lv: 0xFF5C83 };
const STRENGTH = { ra: 0.08, la: 0.08, rv: 0.12, lv: 0.12 };
const DEBUG = new URLSearchParams(location.search).has('debug');

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
  float wi = 1.0 - smoothstep(uRadii[i], uRadii[i] * 1.6, d);   // full inside the radius, gone at 1.6 radii
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
gl_FragColor.rgb += cardioGlow * 0.12;
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
    this.markers = [];
    this.state = { rotate: false, wireframe: false, opacity: 1, cutaway: false };

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.localClippingEnabled = true;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(30, 1, 0.01, 100);
    this.camera.position.set(0, 0.1, 4.4);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.enablePan = false;
    this.controls.minDistance = 1.5;
    this.controls.maxDistance = 9;
    this.controls.autoRotateSpeed = 1.5;

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(2, 3, 4);
    const rim = new THREE.DirectionalLight(0x5B9BFF, 0.7);
    rim.position.set(-3, 1, -3);
    this.scene.add(key, rim, new THREE.AmbientLight(0xffffff, 0.2));

    // shared per chamber index (ra, la, rv, lv); centers and radii are per material, in its local units
    this.uAct = { value: [0, 0, 0, 0] };
    this.uStrength = { value: CHAMBERS.map((c) => STRENGTH[c]) };
    this.uGlow = { value: CHAMBERS.map((c) => new THREE.Color(GLOW[c])) };
    this.centersWorld = CHAMBERS.map(() => new THREE.Vector3());
    this.anchorsWorld = CHAMBERS.map(() => new THREE.Vector3());
    this.normalsWorld = CHAMBERS.map(() => new THREE.Vector3(0, 0, 1));
    this.radiiWorld = [0.45, 0.45, 0.6, 0.6];
    this.backView = false;   // true while the camera looks at the back of the heart
    this.bounds = null;
    this.metrics = null;     // projected extents and the floor point, for the stage decoration
    this.clipPlane = new THREE.Plane(new THREE.Vector3(0, 0, -1), 0.1);

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
    const inner = new THREE.Group();
    inner.add(root);
    root.position.sub(center);
    inner.scale.setScalar(s);
    holder.add(inner);
    if (this.config?.rotation) holder.rotation.set(...this.config.rotation.map((d) => (d * Math.PI) / 180));
    this.scene.add(holder);
    this.model = holder;
    holder.updateMatrixWorld(true);
    const wb = new THREE.Box3().setFromObject(holder);
    this.bounds = wb;
    const f = (v) => v.toArray().map((x) => x.toFixed(2)).join(',');
    console.log(`heart model: raw size ${f(size)}; normalized bounds ${f(wb.min)} to ${f(wb.max)}`);

    if (this.config?.camera) {
      if (this.config.camera.position) this.camera.position.fromArray(this.config.camera.position);
      if (this.config.camera.target) this.controls.target.fromArray(this.config.camera.target);
    }
    const params = new URLSearchParams(location.search);
    const yaw = Number(params.get('yaw') || 0);
    const pitch = Number(params.get('pitch') || 0);
    if (yaw || pitch) {   // debug: orbit the camera for screenshot checks
      const off = this.camera.position.clone().sub(this.controls.target);
      off.applyAxisAngle(new THREE.Vector3(1, 0, 0), (pitch * Math.PI) / 180);
      off.applyAxisAngle(new THREE.Vector3(0, 1, 0), (yaw * Math.PI) / 180);
      this.camera.position.copy(this.controls.target).add(off);
    }
    this.controls.update();

    root.traverse((obj) => {
      if (!obj.isMesh) return;
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
      for (const mat of mats) this.patch(mat, obj);
    });

    if (DEBUG) {
      this.scene.add(new THREE.Box3Helper(wb, 0xffff00));
      this.scene.add(new THREE.AxesHelper(1.2));
      this.markers = CHAMBERS.map((c) => {
        const m = new THREE.Mesh(new THREE.SphereGeometry(0.05, 16, 12),
          new THREE.MeshBasicMaterial({ color: GLOW[c], depthTest: false }));
        m.renderOrder = 10;
        this.scene.add(m);
        return m;
      });
      this.anchorMarkers = CHAMBERS.map(() => {
        const m = new THREE.Mesh(new THREE.SphereGeometry(0.035, 12, 8),
          new THREE.MeshBasicMaterial({ color: 0xffffff, wireframe: true, depthTest: false }));
        m.renderOrder = 11;
        this.scene.add(m);
        return m;
      });
    }
    this.applyConfig();
    for (const el of Object.values(this.labels)) el.hidden = false;
    if (this.missingEl) this.missingEl.hidden = true;
    return true;
  }

  patch(mat, mesh) {
    const uCenters = { value: CHAMBERS.map(() => new THREE.Vector3()) };
    const uRadii = { value: [1, 1, 1, 1] };
    mat.userData.uCenters = uCenters;
    mat.userData.uRadii = uRadii;
    mat.userData.mesh = mesh;
    mat.side = THREE.DoubleSide;
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.uCenters = uCenters;
      shader.uniforms.uRadii = uRadii;
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

  // Chamber centers and radii come from heart.json, in world units of the normalized model.
  applyConfig() {
    const cfg = this.config?.chambers || {};
    CHAMBERS.forEach((c, i) => {
      const ch = cfg[c] || {};
      if (ch.center) this.centersWorld[i].fromArray(ch.center);
      if (ch.radius != null) this.radiiWorld[i] = ch.radius;
      this.anchorsWorld[i].fromArray(ch.anchor || ch.center || [0, 0, 0]);
      if (ch.normal) this.normalsWorld[i].fromArray(ch.normal).normalize();
      else this.normalsWorld[i].copy(this.anchorsWorld[i]).normalize();
    });
    const scaleVec = new THREE.Vector3();
    for (const mat of this.materials) {
      const mesh = mat.userData.mesh;
      mesh.updateMatrixWorld(true);
      mesh.matrixWorld.decompose(new THREE.Vector3(), new THREE.Quaternion(), scaleVec);
      const worldPerLocal = Math.max(scaleVec.x, scaleVec.y, scaleVec.z) || 1;
      this.centersWorld.forEach((cw, i) => {
        mat.userData.uCenters.value[i].copy(cw);
        mesh.worldToLocal(mat.userData.uCenters.value[i]);
        mat.userData.uRadii.value[i] = this.radiiWorld[i] / worldPerLocal;
      });
    }
    this.markers.forEach((m, i) => m.position.copy(this.centersWorld[i]));
    (this.anchorMarkers || []).forEach((m, i) => m.position.copy(this.anchorsWorld[i]));
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

  setOpacity(o) {
    o = Math.min(1, Math.max(0.05, o));
    const wasTransparent = this.state.opacity < 1;
    this.state.opacity = o;
    for (const m of this.materials) {
      m.transparent = o < 1;
      m.opacity = o;
      m.depthWrite = o >= 1;
      if ((o < 1) !== wasTransparent) m.needsUpdate = true;
    }
  }

  setCutaway(on) {
    this.state.cutaway = on;
    for (const m of this.materials) {
      m.clippingPlanes = on ? [this.clipPlane] : [];
      m.needsUpdate = true;
    }
  }

  // Labels live in fixed slots beside the heart: RA and RV on one side, LA and LV on the other.
  // The slots hug the heart's projected outline, swap sides once when the camera goes behind the
  // heart, and ease into place with CSS. Leaders run from the label's real position to the anchor.
  placeLabels() {
    if (!this.model || !this.bounds) return;
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    const p = new THREE.Vector3();
    const toCam = new THREE.Vector3();

    // which side of the heart is the camera on (with hysteresis)
    const v = this.camera.position.clone().sub(this.controls.target);
    const yaw = Math.abs(Math.atan2(v.x, v.z)) * (180 / Math.PI);
    if (!this.backView && yaw > 100) this.backView = true;
    else if (this.backView && yaw < 80) this.backView = false;

    // projected extents of the heart
    let minX = Infinity, maxX = -Infinity;
    const { min, max } = this.bounds;
    for (const x of [min.x, max.x]) for (const y of [min.y, max.y]) for (const z of [min.z, max.z]) {
      p.set(x, y, z).project(this.camera);
      const sx = (p.x * 0.5 + 0.5) * w;
      if (sx < minX) minX = sx;
      if (sx > maxX) maxX = sx;
    }
    p.set(0, min.y + 0.04, 0).project(this.camera);
    this.metrics = { minX, maxX, width: maxX - minX, centerX: (p.x * 0.5 + 0.5) * w, floorY: (-p.y * 0.5 + 0.5) * h };

    const items = CHAMBERS.map((c, i) => {
      const el = this.labels[c];
      if (!el) return null;
      p.copy(this.anchorsWorld[i]).project(this.camera);
      const ax = (p.x * 0.5 + 0.5) * w;
      const ay = (-p.y * 0.5 + 0.5) * h;
      toCam.copy(this.camera.position).sub(this.anchorsWorld[i]);
      const facing = this.normalsWorld[i].dot(toCam) > 0;
      const naturalLeft = c === 'ra' || c === 'rv';
      const left = naturalLeft !== this.backView;
      return { c, el, ax, ay, facing, left, y: ay };
    }).filter(Boolean);

    for (const left of [true, false]) {
      const group = items.filter((it) => it.left === left).sort((a, b) => a.ay - b.ay);
      for (let k = 1; k < group.length; k++) {
        const gap = group[k - 1].el.offsetHeight + 16;
        if (group[k].y < group[k - 1].y + gap) group[k].y = group[k - 1].y + gap;
      }
      const last = group[group.length - 1];
      if (last) {
        const over = last.y + last.el.offsetHeight / 2 - (h - 70);
        if (over > 0) for (const it of group) it.y -= over;
      }
    }

    const margin = 28;
    for (const it of items) {
      const { el } = it;
      el.classList.toggle('side-left', it.left);
      el.classList.toggle('side-right', !it.left);
      el.classList.toggle('dim', !it.facing);
      const title = el.querySelector('b');
      const titleMid = title ? title.offsetTop + title.offsetHeight / 2 : 20;
      const lw = el.offsetWidth;
      let x;
      if (it.left) x = Math.max(12, Math.min(minX - margin, w * 0.42) - lw);
      else x = Math.min(w - 12 - lw, Math.max(maxX + margin, w * 0.58));
      el.style.left = `${Math.round(x)}px`;
      el.style.top = `${Math.round(it.y - titleMid)}px`;
    }

    // leaders start where the label really is (CSS may still be easing it)
    const box = this.container.getBoundingClientRect();
    let svg = '';
    for (const it of items) {
      const r = it.el.getBoundingClientRect();
      const title = it.el.querySelector('b');
      const titleMid = title ? title.offsetTop + title.offsetHeight / 2 : 20;
      const sx = (it.left ? r.right : r.left) - box.left;
      const sy = r.top - box.top + titleMid;
      const knee = it.left ? sx + 26 : sx - 26;
      const cls = it.facing ? '' : ' class="dim"';
      svg += `<polyline${cls} fill="none" points="${sx.toFixed(1)},${sy.toFixed(1)} ${knee.toFixed(1)},${sy.toFixed(1)} ${it.ax.toFixed(1)},${it.ay.toFixed(1)}"></polyline>`;
      svg += `<circle${cls} cx="${it.ax.toFixed(1)}" cy="${it.ay.toFixed(1)}" r="4"></circle>`;
    }
    if (this.leaders) this.leaders.innerHTML = svg;
  }

  render() {
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.placeLabels();
  }
}
