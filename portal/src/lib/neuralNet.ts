/**
 * Red cognitiva espacial: simulación pura (sin DOM) de la escena viva del acceso.
 *
 * No dibuja nada: genera y hace evolucionar un sistema de nodos y enlaces con
 * tres planos de profundidad. Los impulsos viajan por los enlaces, excitan el
 * nodo de llegada y se propagan; algunas rutas se atenúan y vuelven con un ciclo
 * lento, así la topología parece plástica sin reconstruirse.
 *
 * El espacio es el del canvas (px) para que la densidad siga al viewport. Todo
 * es determinista por seed: mismo tamaño + misma semilla = misma red.
 */

export type NetRole = "hub" | "relay" | "leaf";
export type NetTone = "signal" | "deep" | "flash" | "alert";
/** 0 = primer plano, 2 = fondo. */
export type NetPlane = 0 | 1 | 2;
export type NetZone = "email" | "password";

export type NetNode = {
  x: number;
  y: number;
  /** 0 = cerca, 1 = lejos. Ordena tamaño, alfa y parallax. */
  z: number;
  plane: NetPlane;
  radius: number;
  /** 0..1.5: sube al disparar y decae. */
  energy: number;
  /** Segundos que faltan para poder volver a disparar. */
  refractory: number;
  role: NetRole;
  /** Pertenencia a una ruta de foco (email / contraseña). */
  zone: NetZone | null;
  phase: number;
  /** Desplazamiento respecto de la posición de reposo (resorte). */
  vx: number;
  vy: number;
  dvx: number;
  dvy: number;
};

export type NetEdge = {
  a: number;
  b: number;
  /** Punto de control del bezier: curvatura del tracto. */
  cx: number;
  cy: number;
  /** 0..1: qué tan fuerte conduce. */
  weight: number;
  phase: number;
  /** Período en ms de aparición/desaparición; 0 = siempre visible. */
  cycle: number;
  length: number;
  /** Plano en el que se dibuja (el del extremo más lejano). */
  plane: NetPlane;
};

export type NetPulse = {
  edge: number;
  /** 0..1 recorrido. */
  t: number;
  /** px por segundo. */
  speed: number;
  /** 1: a→b, -1: b→a. */
  dir: 1 | -1;
  strength: number;
  tone: NetTone;
};

export type NetWave = {
  x: number;
  y: number;
  r: number;
  alpha: number;
  tone: NetTone;
};

export type NeuralNet = {
  width: number;
  height: number;
  seed: number;
  compact: boolean;
  nodes: NetNode[];
  edges: NetEdge[];
  /** nodo → índices de enlaces que salen de él. */
  outgoing: number[][];
  hubs: number[];
  pulses: NetPulse[];
  wave: NetWave | null;
  time: number;
  /** Llegadas de señal en la última ventana de 1 s (medido). */
  rate: number;
  firings: number[];
  nextSpontaneousIn: number;
  nextBurstIn: number;
  /** 0..1 por ruta: cuánto está iluminada. */
  focus: Record<NetZone, number>;
  focusZone: NetZone | null;
  /** 0..1: presión de envío (sube al autenticar). */
  submit: number;
  /** 0..1: rechazo (el sistema se contrae). */
  recoil: number;
  /** 0..1: acceso concedido (destello). */
  success: number;
  random: () => number;
};

export type NetStats = {
  /** Nodos de la red. */
  neurons: number;
  /** Enlaces entre nodos. */
  synapses: number;
  /** Llegadas de señal por segundo. */
  rate: number;
  /** Enlaces conduciendo en este instante. */
  active: number;
};

export const REFRACTORY_SECONDS = 0.085;
export const MAX_PULSE_RATIO = 0.95;
const TAU = Math.PI * 2;

/** PRNG determinista (mulberry32). */
export function createRandom(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Masa cortical abstracta: gaussianas orientadas superpuestas. No se dibuja el
 * contorno; sólo decide dónde se concentran los nodos, para que la red tenga
 * "cuerpo" sin volverse una ilustración anatómica.
 */
type Blob = { x: number; y: number; rx: number; ry: number; rot: number; w: number };

const CORTEX: Blob[] = [
  { x: 0.4, y: 0.45, rx: 0.3, ry: 0.21, rot: -0.2, w: 1 },
  { x: 0.58, y: 0.27, rx: 0.19, ry: 0.11, rot: -0.08, w: 0.72 },
  { x: 0.33, y: 0.66, rx: 0.15, ry: 0.1, rot: 0.12, w: 0.58 },
  { x: 0.7, y: 0.55, rx: 0.11, ry: 0.09, rot: 0, w: 0.42 },
  { x: 0.6, y: 0.8, rx: 0.05, ry: 0.09, rot: 0, w: 0.38 },
];

function massAt(nx: number, ny: number): number {
  let mass = 0;
  for (const blob of CORTEX) {
    const dx = nx - blob.x;
    const dy = ny - blob.y;
    const cos = Math.cos(blob.rot);
    const sin = Math.sin(blob.rot);
    const u = (dx * cos + dy * sin) / blob.rx;
    const v = (-dx * sin + dy * cos) / blob.ry;
    mass += blob.w * Math.exp(-0.5 * (u * u + v * v));
  }
  return Math.min(1, mass);
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function planeOf(z: number): NetPlane {
  if (z < 0.34) return 0;
  if (z < 0.67) return 1;
  return 2;
}

export function createNeuralNet(options: {
  width: number;
  height: number;
  seed?: number;
  /** 1 = densidad de escritorio; <1 para móvil. */
  density?: number;
}): NeuralNet {
  const width = Math.max(1, options.width);
  const height = Math.max(1, options.height);
  const seed = options.seed ?? 20260926;
  const density = options.density ?? 1;
  const random = createRandom(seed);
  const compact = width < 1024;

  // Cuántos nodos: proporcional al área, con techo para no castigar GPUs lentas.
  const target = clamp(Math.round(((width * height) / 16000) * density), 40, 148);
  const minDim = Math.min(width, height);

  const nodes: NetNode[] = [];
  let guard = 0;
  while (nodes.length < target && guard < target * 90) {
    guard += 1;
    const nx = random();
    const ny = random();
    const mass = massAt(nx, ny);
    // 14% satélites fuera de la masa: rompen el óvalo y dan lectura de red.
    const satellite = random() < 0.14;
    if (satellite ? mass > 0.42 : random() > mass * 0.94) continue;

    const roll = random();
    const role: NetRole = roll < 0.07 ? "hub" : roll < 0.4 ? "relay" : "leaf";
    const z = (random() + random()) / 2;
    nodes.push({
      x: nx * width,
      y: ny * height,
      z,
      plane: planeOf(z),
      radius:
        role === "hub" ? 2.3 + random() * 1.1 : role === "relay" ? 1.5 + random() * 0.8 : 0.9 + random() * 0.7,
      energy: random() * 0.18,
      refractory: 0,
      role,
      zone: null,
      phase: random() * TAU,
      vx: 0,
      vy: 0,
      dvx: 0,
      dvy: 0,
    });
  }

  const edges: NetEdge[] = [];
  const seen = new Set<string>();
  const connect = (a: number, b: number, weight: number): boolean => {
    const lo = Math.min(a, b);
    const hi = Math.max(a, b);
    if (lo === hi) return false;
    const key = `${lo}:${hi}`;
    if (seen.has(key)) return false;
    seen.add(key);
    const from = nodes[lo];
    const to = nodes[hi];
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const length = Math.hypot(dx, dy);
    // Curvatura siempre presente (nunca un segmento recto) y mayor en tractos largos.
    const bend = (0.07 + random() * 0.26) * (random() < 0.5 ? -1 : 1) * length;
    edges.push({
      a: lo,
      b: hi,
      cx: (from.x + to.x) / 2 - dy * bend * 1.55,
      cy: (from.y + to.y) / 2 + dx * bend * 1.55,
      weight,
      phase: random() * TAU,
      cycle: random() < 0.13 ? 2400 + random() * 5600 : 0,
      length,
      plane: Math.max(from.plane, to.plane) as NetPlane,
    });
    return true;
  };

  // Vecindad: cada nodo se enlaza a los más cercanos. Los hubs alcanzan más
  // lejos: son las rutas largas que dan la lectura de "red conectada".
  const wanted: Record<NetRole, number> = { hub: 9, relay: 5, leaf: 3 };
  const reach = minDim * (compact ? 0.3 : 0.2);
  for (let i = 0; i < nodes.length; i += 1) {
    const from = nodes[i];
    const order = nodes
      .map((to, index) => ({ index, d: Math.hypot(to.x - from.x, to.y - from.y) }))
      .filter((entry) => entry.index !== i)
      .sort((p, q) => p.d - q.d);
    let made = 0;
    for (const candidate of order) {
      if (made >= wanted[from.role]) break;
      // Los dos primeros enlaces se garantizan aunque el vecino esté lejos.
      if (candidate.d > reach * (made < 2 ? 1.15 : 1)) break;
      if (random() < 0.24) continue;
      if (connect(i, candidate.index, clamp(1 - candidate.d / (reach * 1.6), 0.18, 1))) made += 1;
    }
  }

  // Tractos largos entre hubs: unos pocos cruces de extremo a extremo, con tope
  // de longitud para que la red no se lea como rayones sobre el fondo.
  const hubIndices = nodes
    .map((node, index) => ({ node, index }))
    .filter((entry) => entry.node.role === "hub")
    .map((entry) => entry.index);
  for (const hub of hubIndices) {
    const links = 2 + Math.floor(random() * 3);
    for (let k = 0; k < links; k += 1) {
      const other = hubIndices[Math.floor(random() * hubIndices.length)];
      if (other === undefined || other === hub) continue;
      const from = nodes[hub];
      const to = nodes[other];
      if (Math.hypot(to.x - from.x, to.y - from.y) > minDim * 0.42) continue;
      connect(hub, other, 0.42 + random() * 0.25);
    }
  }

  // Garantía de conectividad: sin esto, un canvas diminuto (tests, 1×1) o un
  // viewport extremo podrían dejar la red casi sin enlaces. Se enlazan vecinos
  // reales, nunca pares lejanos.
  guard = 0;
  while (edges.length < nodes.length * 1.35 && guard < nodes.length * 8) {
    guard += 1;
    const a = Math.floor(random() * nodes.length);
    const near = nodes
      .map((node, index) => ({
        index,
        d: Math.hypot(node.x - nodes[a].x, node.y - nodes[a].y),
      }))
      .filter((entry) => entry.index !== a)
      .sort((p, q) => p.d - q.d)
      .slice(0, 14);
    for (const candidate of near) {
      if (connect(a, candidate.index, 0.22 + random() * 0.3)) break;
    }
  }

  const outgoing: number[][] = nodes.map(() => []);
  edges.forEach((edge, index) => {
    outgoing[edge.a].push(index);
    outgoing[edge.b].push(index);
  });

  return {
    width,
    height,
    seed,
    compact,
    nodes,
    edges,
    outgoing,
    hubs: hubIndices,
    pulses: [],
    wave: null,
    time: 0,
    rate: 0,
    firings: [],
    nextSpontaneousIn: 0.15,
    nextBurstIn: 3 + random() * 3,
    focus: { email: 0, password: 0 },
    focusZone: null,
    submit: 0,
    recoil: 0,
    success: 0,
    random: createRandom(seed ^ 0x9e3779b9),
  };
}

/**
 * Marca qué nodos forman cada ruta de foco. En escritorio viven junto al borde
 * izquierdo de la tarjeta; en móvil son el racimo que queda detrás del
 * encabezado. Si el ancla cae en zona vacía, se toman los más cercanos.
 */
export function assignZones(net: NeuralNet, layout: { compact: boolean }): void {
  const anchors: Record<NetZone, { x: number; y: number }> = layout.compact
    ? { email: { x: 0.5, y: 0.15 }, password: { x: 0.5, y: 0.32 } }
    : { email: { x: 0.6, y: 0.36 }, password: { x: 0.6, y: 0.56 } };
  const radius = Math.min(net.width, net.height) * 0.18;
  for (const zone of ["email", "password"] as const) {
    const anchor = anchors[zone];
    const candidates = net.nodes
      .map((node, index) => ({
        index,
        d: Math.hypot(node.x - anchor.x * net.width, node.y - anchor.y * net.height),
      }))
      .sort((p, q) => p.d - q.d);
    let marked = 0;
    for (const candidate of candidates) {
      if (marked >= 12) break;
      if (net.nodes[candidate.index].zone) continue;
      if (candidate.d > radius && marked >= 5) break;
      net.nodes[candidate.index].zone = zone;
      marked += 1;
    }
  }
}

function spawnFrom(net: NeuralNet, index: number, strength: number, tone: NetTone): void {
  const options = net.outgoing[index];
  if (!options.length) return;
  const budget = Math.min(options.length, 2);
  for (let i = 0; i < budget; i += 1) {
    const edgeIndex = options[Math.floor(net.random() * options.length)];
    const edge = net.edges[edgeIndex];
    if (!edge) continue;
    const limit = Math.max(30, Math.round(net.nodes.length * MAX_PULSE_RATIO));
    if (net.pulses.length >= limit) return;
    if (net.random() > 0.42 + edge.weight * 0.48) continue;
    net.pulses.push({
      edge: edgeIndex,
      t: 0,
      speed: 70 + net.random() * 60,
      dir: edge.a === index ? 1 : -1,
      strength: Math.max(0.2, strength * (0.55 + edge.weight * 0.6)),
      tone,
    });
  }
}

/** Dispara un nodo: marca energía, registra el evento y propaga. */
export function fire(net: NeuralNet, index: number, strength = 1, tone: NetTone = "signal"): boolean {
  const node = net.nodes[index];
  if (!node || node.refractory > 0) return false;
  node.energy = Math.min(1.5, node.energy + strength);
  node.refractory = REFRACTORY_SECONDS;
  net.firings.push(net.time);
  spawnFrom(net, index, strength, tone);
  return true;
}

/** Descarga: varios hubs disparan a la vez y la señal se reparte. */
export function burst(net: NeuralNet, strength = 1.2): number {
  if (!net.hubs.length) return 0;
  let fired = 0;
  for (let i = 0; i < 4; i += 1) {
    const index = net.hubs[Math.floor(net.random() * net.hubs.length)];
    net.nodes[index].refractory = 0;
    if (fire(net, index, strength)) fired += 1;
  }
  return fired;
}

/** Enciende la ruta de un campo: el sistema "escucha" esa zona y manda
 *  señales hacia el resto de la red (visibles, no sólo un brillo local). */
export function setFocus(net: NeuralNet, zone: NetZone | null): void {
  net.focusZone = zone;
  if (!zone) return;
  net.focus[zone] = 1;
  let lit = 0;
  for (const [index, node] of net.nodes.entries()) {
    if (node.zone !== zone) continue;
    node.refractory = 0;
    if (fire(net, index, 0.9 + net.random() * 0.4)) lit += 1;
    if (lit >= 3) break;
  }
  // Tres impulsos salen de la ruta hacia la izquierda: se lee el disparo.
  let sent = 0;
  for (const [index, node] of net.nodes.entries()) {
    if (node.zone !== zone) continue;
    const leftward = net.outgoing[index].filter((edgeIndex) => {
      const edge = net.edges[edgeIndex];
      const other = edge.a === index ? edge.b : edge.a;
      return net.nodes[other].x < node.x - net.width * 0.04;
    });
    if (!leftward.length) continue;
    const pick = leftward[Math.floor(net.random() * leftward.length)];
    net.pulses.push({
      edge: pick,
      t: 0,
      speed: 95 + net.random() * 55,
      dir: net.edges[pick].a === index ? 1 : -1,
      strength: 1.05,
      tone: "signal",
    });
    sent += 1;
    if (sent >= 3) break;
  }
}

/** Los nodos más cercanos a un punto: origen de la chispa de envío. */
function nearestNodes(net: NeuralNet, x: number, y: number, count: number): number[] {
  return net.nodes
    .map((node, index) => ({ index, d: Math.hypot(node.x - x, node.y - y) }))
    .sort((p, q) => p.d - q.d)
    .slice(0, count)
    .map((entry) => entry.index);
}

/**
 * Envío: la solicitud entra al sistema. Nace una onda en el borde de la
 * tarjeta, la red se enciende a su paso y sube la frecuencia de disparo.
 */
export function triggerSubmit(net: NeuralNet): void {
  net.submit = Math.min(1, net.submit + 1);
  const x = net.width * (net.compact ? 0.5 : 0.62);
  const y = net.height * (net.compact ? 0.4 : 0.46);
  net.wave = { x, y, r: 0, alpha: 0.85, tone: "signal" };
  for (const index of nearestNodes(net, x, y, 6)) {
    net.nodes[index].refractory = 0;
    fire(net, index, 1.15);
  }
}

/** Rechazo: la red se contrae y quedan pulsos de alerta. */
export function triggerError(net: NeuralNet): void {
  net.recoil = 1;
  net.submit = 0;
  net.wave = null;
  for (const index of nearestNodes(net, net.width * 0.5, net.height * 0.5, 4)) {
    net.nodes[index].refractory = 0;
    fire(net, index, 0.8, "alert");
  }
}

/** Acceso concedido: destello y descarga general antes de salir. */
export function triggerSuccess(net: NeuralNet): void {
  net.success = 1;
  net.recoil = 0;
  net.wave = { x: net.width * 0.5, y: net.height * 0.45, r: 0, alpha: 0.7, tone: "flash" };
  burst(net, 1.5);
  burst(net, 1.15);
}

/**
 * El puntero empuja los nodos cercanos (resorte, vuelven solos) y excita la
 * zona: la red reacciona a la persona sin perseguirla.
 */
export function excitePointer(net: NeuralNet, x: number, y: number, power = 1): number {
  const radius = Math.min(net.width, net.height) * 0.09;
  const candidates: { index: number; d: number }[] = [];
  for (let index = 0; index < net.nodes.length; index += 1) {
    const node = net.nodes[index];
    const dx = node.x - x;
    const dy = node.y - y;
    const d = Math.hypot(dx, dy);
    if (d > radius) continue;
    const push = (1 - d / radius) * 34 * power;
    if (d > 0.001) {
      node.dvx += (dx / d) * push;
      node.dvy += (dy / d) * push;
    }
    candidates.push({ index, d });
  }
  candidates.sort((p, q) => p.d - q.d);
  let fired = 0;
  for (const candidate of candidates) {
    if (fired >= 2) break;
    if (net.nodes[candidate.index].refractory > 0) continue;
    if (fired > 0 && net.random() < 0.5) continue;
    if (fire(net, candidate.index, 0.55 * power)) fired += 1;
  }
  return fired;
}

/** Avanza la simulación `dt` segundos. */
export function stepNeuralNet(net: NeuralNet, dt: number): void {
  const step = clamp(dt, 0, 1 / 30);
  if (step === 0) return;
  net.time += step;

  net.submit = Math.max(0, net.submit - step * 0.55);
  net.recoil = Math.max(0, net.recoil - step * 0.9);
  net.success = Math.max(0, net.success - step * 0.55);
  for (const zone of ["email", "password"] as const) {
    if (net.focusZone !== zone) net.focus[zone] = Math.max(0, net.focus[zone] - step * 0.5);
  }

  for (const node of net.nodes) {
    // Resorte críticamente sub-amortiguado: el desplazamiento vuelve solo.
    node.dvx += (-26 * node.vx - 6.5 * node.dvx) * step;
    node.dvy += (-26 * node.vy - 6.5 * node.dvy) * step;
    node.vx += node.dvx * step;
    node.vy += node.dvy * step;
    node.energy = Math.max(0, node.energy - step * 1.45);
    if (node.refractory > 0) node.refractory = Math.max(0, node.refractory - step);
  }

  if (net.wave) {
    const wave = net.wave;
    wave.r += step * Math.min(net.width, net.height) * 0.62;
    wave.alpha = Math.max(0, wave.alpha - step * 0.5);
    for (let index = 0; index < net.nodes.length; index += 1) {
      const node = net.nodes[index];
      if (node.refractory > 0) continue;
      const d = Math.hypot(node.x - wave.x, node.y - wave.y);
      if (Math.abs(d - wave.r) < 30 && net.random() < 0.09) {
        fire(net, index, 0.7 + net.submit * 0.5, wave.tone);
      }
    }
    if (wave.alpha <= 0 || wave.r > Math.hypot(net.width, net.height)) net.wave = null;
  }

  const survivors: NetPulse[] = [];
  for (const pulse of net.pulses) {
    const edge = net.edges[pulse.edge];
    if (!edge) continue;
    pulse.t += (step * pulse.speed) / Math.max(1, edge.length);
    if (pulse.t >= 1) {
      const target = pulse.dir === 1 ? edge.b : edge.a;
      fire(
        net,
        target,
        pulse.strength * (net.recoil > 0.5 ? 0.35 : 1),
        pulse.tone === "alert" ? "alert" : "signal"
      );
      continue;
    }
    survivors.push(pulse);
  }
  net.pulses = survivors;

  // Actividad espontánea: el sistema nunca se apaga; con el envío se acelera.
  net.nextSpontaneousIn -= step;
  if (net.nextSpontaneousIn <= 0) {
    net.nextSpontaneousIn = (0.14 + net.random() * 0.42) / (1 + net.submit * 1.8);
    fire(net, Math.floor(net.random() * net.nodes.length), 0.85 + net.submit * 0.4);
  }

  // Descargas: un evento cada varios segundos, no ruido constante.
  net.nextBurstIn -= step * (1 + net.submit * 1.4);
  if (net.nextBurstIn <= 0) {
    net.nextBurstIn = 5.5 + net.random() * 5;
    burst(net, 1.05 + net.submit * 0.5);
  }

  const cutoff = net.time - 1;
  while (net.firings.length && net.firings[0] < cutoff) net.firings.shift();
  net.rate = net.firings.length;
}

/** Cuántos enlaces están conduciendo ahora. */
export function activePulses(net: NeuralNet): number {
  return net.pulses.length;
}

export function netStats(net: NeuralNet): NetStats {
  return {
    neurons: net.nodes.length,
    synapses: net.edges.length,
    rate: net.rate,
    active: net.pulses.length,
  };
}
