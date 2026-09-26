/**
 * Campo neuronal: simulación pura (sin DOM) del cerebro que se dibuja en las
 * pantallas de acceso.
 *
 * Genera una silueta de cerebro con pliegues corticales, la conecta con
 * sinapsis (vecinas + tractos largos curvos) y hace viajar pulsos que excitan
 * las neuronas al llegar, propagando la actividad. Todo determinista por seed:
 * el mismo seed produce siempre el mismo cerebro, así el render es estable y
 * testeable.
 *
 * Las métricas son reales: `rate` cuenta llegadas de los últimos 1000 ms.
 */

export type NeuronRole = "cortex" | "hub" | "deep";

export type Neuron = {
  x: number;
  y: number;
  /** 0 = primer plano, 1 = profundo (alimenta parallax, tamaño y alfa). */
  depth: number;
  radius: number;
  /** 0..1, sube al disparar y decae. */
  energy: number;
  /** Segundos que faltan para poder volver a disparar. */
  refractory: number;
  role: NeuronRole;
};

export type Synapse = {
  a: number;
  b: number;
  /** Punto de control del bezier: da curvatura a los tractos largos. */
  cx: number;
  cy: number;
  weight: number;
  length: number;
};

export type Pulse = {
  synapse: number;
  /** 0..1 recorrido. */
  t: number;
  /** Recorridos por segundo. */
  speed: number;
  /** 1: a→b, -1: b→a. */
  dir: 1 | -1;
  strength: number;
};

export type NeuralField = {
  seed: number;
  neurons: Neuron[];
  synapses: Synapse[];
  /** neuron index → índices de sinapsis que salen de esa neurona. */
  outgoing: number[][];
  /** Neuronas hub (muy conectadas): origen natural de una descarga. */
  hubs: number[];
  pulses: Pulse[];
  time: number;
  rate: number;
  firings: number[];
  nextSpontaneousIn: number;
  random: () => number;
};

export const RATE_WINDOW_MS = 1000;
export const REFRACTORY_SECONDS = 0.07;
export const MAX_PULSES_PER_NEURON = 1.15;

/** Lóbulos que componen la silueta. El contorno se traza de estas mismas
 *  elipses, así el dibujo y la densidad de neuronas no pueden divergir. */
export const LOBES: { cx: number; cy: number; rx: number; ry: number; taper: boolean }[] = [
  { cx: 0.45, cy: 0.42, rx: 0.4, ry: 0.265, taper: true }, // frontal-parietal
  { cx: 0.42, cy: 0.665, rx: 0.235, ry: 0.145, taper: true }, // temporal
  { cx: 0.8, cy: 0.695, rx: 0.1, ry: 0.07, taper: false }, // cerebelo
  { cx: 0.672, cy: 0.83, rx: 0.048, ry: 0.125, taper: false }, // tronco
];

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

function ellipse(x: number, y: number, cx: number, cy: number, rx: number, ry: number): number {
  const dx = (x - cx) / rx;
  const dy = (y - cy) / ry;
  return 1 - (dx * dx + dy * dy);
}

/** El lóbulo frontal-parietal se afina hacia el occipital. */
function taperAt(x: number): number {
  return x < 0.62 ? 1 : 1 - Math.min(1, (x - 0.62) / 0.34) * 0.5;
}

function lobeField(index: number, x: number, y: number): number {
  const lobe = LOBES[index];
  if (!lobe) return -1;
  const ry = lobe.taper ? lobe.ry * taperAt(x) : lobe.ry;
  return ellipse(x, y, lobe.cx, lobe.cy, lobe.rx, ry);
}

/** Seno de la fisura lateral (surco de Silvio): separa el lóbulo temporal. */
function fissureY(x: number): number {
  return 0.605 + 0.075 * Math.sin((x - 0.12) * 5.4) + 0.02 * Math.cos(x * 9);
}

/**
 * Pertenencia al cerebro: >0 dentro, <=0 fuera.
 */
export function brainField(x: number, y: number): number {
  let inside = -1;
  for (let i = 0; i < LOBES.length; i += 1) inside = Math.max(inside, lobeField(i, x, y));
  if (inside <= 0) return inside;
  // El surco hunde la densidad: pliega la corteza sin romper la silueta.
  const sulcus = y - fissureY(x);
  const sulcusDip = Math.exp(-(sulcus * sulcus) / 0.00055);
  return inside * (1 - 0.8 * sulcusDip);
}

/** Densidad de pliegues (giros) sobre la cinta cortical. */
export function foldDensity(x: number, y: number): number {
  const a = Math.sin(x * 41 + y * 15);
  const b = Math.sin(x * 13 - y * 33);
  const c = Math.cos(x * 26 + y * 37);
  return 0.4 + 0.6 * Math.max(0, (a + b + c) / 3 + 0.4);
}

/** Distancia normalizada al borde (0 = borde, 1 = centro). */
export function interiorDepth(x: number, y: number): number {
  const step = 0.012;
  const here = brainField(x, y);
  if (here <= 0) return 0;
  const spread =
    (brainField(x + step, y) + brainField(x - step, y) + brainField(x, y + step) + brainField(x, y - step)) /
    4;
  const gradient = Math.max(0, here - spread) / step;
  return Math.max(0, Math.min(1, here / (gradient + 0.6)));
}

/**
 * Contorno del cerebro: un lazo por lóbulo, recortado a la frontera EXTERIOR.
 *
 * Cada lazo se obtiene marchando el radio desde el centro del lóbulo hasta el
 * cruce por cero. Los tramos que caen dentro de otro lóbulo se descartan, así el
 * resultado es la silueta del conjunto y no un puñado de elipses superpuestas.
 */
export function brainContours(samples = 260): { x: number; y: number }[][] {
  const loops: { x: number; y: number }[][] = [];
  LOBES.forEach((lobe, index) => {
    let current: { x: number; y: number }[] = [];
    for (let i = 0; i <= samples; i += 1) {
      const angle = (i / samples) * Math.PI * 2;
      const dirX = Math.cos(angle);
      const dirY = Math.sin(angle);
      let low = 0;
      let high = Math.max(lobe.rx, lobe.ry) * 1.6;
      if (lobeField(index, lobe.cx + dirX * high, lobe.cy + dirY * high) > 0) {
        high *= 1.2; // el taper puede estirar el borde en x
      }
      for (let step = 0; step < 22; step += 1) {
        const mid = (low + high) / 2;
        if (lobeField(index, lobe.cx + dirX * mid, lobe.cy + dirY * mid) > 0) low = mid;
        else high = mid;
      }
      const point = { x: lobe.cx + dirX * low, y: lobe.cy + dirY * low };
      // ¿Este punto está dentro de otro lóbulo? Entonces es frontera interna.
      if (lobeFieldOther(index, point.x, point.y) > 0.004) {
        if (current.length > 1) loops.push(current);
        current = [];
        continue;
      }
      current.push(point);
    }
    if (current.length > 1) loops.push(current);
  });
  return loops;
}

/** Máximo de los lóbulos distintos de `skip` (sin el surco). */
function lobeFieldOther(skip: number, x: number, y: number): number {
  let value = -1;
  for (let i = 0; i < LOBES.length; i += 1) {
    if (i === skip) continue;
    value = Math.max(value, lobeField(i, x, y));
  }
  return value;
}

/**
 * Surcos interiores: la fisura lateral (Silvio) y una cisura central. Son la
 * pista que hace que el ojo lea "cerebro" y no "globo": sin ellas, la silueta
 * sola no alcanza.
 */
export function brainSulci(samples = 120): { x: number; y: number }[][] {
  const curves: ((x: number) => number)[] = [
    (x) => fissureY(x),
    (x) => 0.34 + 0.14 * Math.sin((x - 0.3) * 4.2) - 0.06 * Math.cos(x * 7),
  ];
  const segments: { x: number; y: number }[][] = [];
  for (const curve of curves) {
    let current: { x: number; y: number }[] = [];
    for (let i = 0; i <= samples; i += 1) {
      const x = 0.05 + (i / samples) * 0.88;
      const y = curve(x);
      if (brainField(x, y) <= 0.02) {
        if (current.length > 2) segments.push(current);
        current = [];
        continue;
      }
      current.push({ x, y });
    }
    if (current.length > 2) segments.push(current);
  }
  return segments;
}

export function createNeuralField(options: { seed?: number; count?: number } = {}): NeuralField {
  const seed = options.seed ?? 1337;
  const count = Math.max(24, options.count ?? 150);
  const random = createRandom(seed);
  const neurons: Neuron[] = [];
  const ribbonTarget = Math.round(count * 0.72);

  // 1. Cinta cortical: la mayoría de las neuronas viven cerca del borde, que es
  //    lo que hace que la silueta se lea como cerebro y no como una nube.
  let guard = 0;
  while (neurons.length < ribbonTarget && guard < count * 600) {
    guard += 1;
    const x = 0.02 + random() * 0.96;
    const y = 0.06 + random() * 0.9;
    if (brainField(x, y) <= 0) continue;
    const depth = interiorDepth(x, y);
    if (depth > 0.3) continue;
    // Pliegues: la cinta se engrosa y se afina a lo largo del contorno.
    if (random() > 0.3 + 0.7 * foldDensity(x, y)) continue;
    neurons.push({
      x,
      y,
      // Cinta cortical: cerca del borde = primer plano (brillante y grande).
      depth: 0.08 + depth * 0.9,
      radius: 0.9 + random() * 0.9,
      energy: random() * 0.25,
      refractory: 0,
      role: "cortex",
    });
  }

  // 2. Estructuras profundas: núcleo central denso + cadena por el tronco.
  const deepTarget = count;
  while (neurons.length < deepTarget && guard < count * 900) {
    guard += 1;
    const x = 0.03 + random() * 0.94;
    const y = 0.08 + random() * 0.88;
    if (brainField(x, y) <= 0) continue;
    const depth = interiorDepth(x, y);
    const stem = x > 0.63 && y > 0.68;
    const core = depth > 0.42 && x < 0.68;
    const chance = stem ? 0.5 : core ? 0.34 : 0.12;
    if (random() > chance) continue;
    neurons.push({
      x,
      y,
      // Estructuras internas: al fondo (tenues y frías) para dar profundidad.
      depth: 0.45 + depth * 0.55,
      radius: 0.8 + random() * 0.9,
      energy: random() * 0.2,
      refractory: 0,
      role: "deep",
    });
  }

  // Hubs: pocas neuronas muy conectadas (los "nodos" que se ven de lejos).
  const hubCount = Math.max(3, Math.round(neurons.length * 0.08));
  for (let i = 0; i < hubCount; i += 1) {
    const pick = Math.floor(random() * neurons.length);
    neurons[pick].role = "hub";
    neurons[pick].radius += 1.6;
  }

  const synapses: Synapse[] = [];
  const seen = new Set<string>();
  const connect = (a: number, b: number, weight: number) => {
    const lo = Math.min(a, b);
    const hi = Math.max(a, b);
    const key = `${lo}:${hi}`;
    if (lo === hi || seen.has(key)) return;
    seen.add(key);
    const from = neurons[lo];
    const to = neurons[hi];
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const length = Math.hypot(dx, dy);
    // Control perpendicular: curvatura mayor en conexiones largas.
    const bend = (random() - 0.5) * 0.5 * length;
    synapses.push({
      a: lo,
      b: hi,
      cx: (from.x + to.x) / 2 - dy * bend * 2.6,
      cy: (from.y + to.y) / 2 + dx * bend * 2.6,
      weight,
      length,
    });
  };

  for (let i = 0; i < neurons.length; i += 1) {
    const from = neurons[i];
    const wanted = from.role === "hub" ? 6 : from.role === "deep" ? 2 : 3;
    const order = neurons
      .map((to, index) => ({ index, d: Math.hypot(to.x - from.x, to.y - from.y) }))
      .filter((entry) => entry.index !== i)
      .sort((a, b) => a.d - b.d);
    let made = 0;
    for (const candidate of order) {
      if (made >= wanted) break;
      const reach = from.role === "hub" ? 0.32 : from.role === "deep" ? 0.16 : 0.1;
      if (candidate.d > reach) break;
      if (random() < 0.28) continue;
      connect(i, candidate.index, 1 - candidate.d / (reach + 0.001));
      made += 1;
    }
  }

  // Tractos largos entre hubs: dan la lectura de "red conectada".
  const hubs = neurons.map((n, index) => ({ n, index })).filter((entry) => entry.n.role === "hub");
  for (const hub of hubs) {
    for (let k = 0; k < 3; k += 1) {
      const target = hubs[Math.floor(random() * hubs.length)];
      if (target && target.index !== hub.index) connect(hub.index, target.index, 0.6);
    }
  }

  const hubIndices = hubs.map((entry) => entry.index);

  const outgoing: number[][] = neurons.map(() => []);
  synapses.forEach((synapse, index) => {
    outgoing[synapse.a].push(index);
    outgoing[synapse.b].push(index);
  });

  return {
    seed,
    neurons,
    synapses,
    outgoing,
    hubs: hubIndices,
    pulses: [],
    time: 0,
    rate: 0,
    firings: [],
    nextSpontaneousIn: 0.2,
    random: createRandom(seed ^ 0x9e3779b9),
  };
}

/** Descarga cortical: varios hubs disparan a la vez y la señal se propaga. */
export function burst(field: NeuralField, strength = 1.35): number {
  if (!field.hubs.length) return 0;
  let fired = 0;
  for (let i = 0; i < 4; i += 1) {
    const index = field.hubs[Math.floor(field.random() * field.hubs.length)];
    field.neurons[index].refractory = 0;
    if (fire(field, index, strength)) fired += 1;
  }
  return fired;
}

export function otherEnd(field: NeuralField, pulse: Pulse): number {
  const synapse = field.synapses[pulse.synapse];
  return pulse.dir === 1 ? synapse.b : synapse.a;
}

function spawnFrom(field: NeuralField, neuron: number, strength: number): void {
  const options = field.outgoing[neuron];
  if (!options.length) return;
  const budget = Math.min(options.length, 2);
  for (let i = 0; i < budget; i += 1) {
    const index = options[Math.floor(field.random() * options.length)];
    const synapse = field.synapses[index];
    if (!synapse) continue;
    const limit = Math.max(24, field.neurons.length * MAX_PULSES_PER_NEURON);
    if (field.pulses.length >= limit) return;
    if (field.random() > 0.35 + synapse.weight * 0.5) continue;
    const dir: 1 | -1 = synapse.a === neuron ? 1 : -1;
    field.pulses.push({
      synapse: index,
      t: 0,
      speed: 0.55 + synapse.length * 1.15,
      dir,
      strength: Math.max(0.18, strength * (0.55 + synapse.weight * 0.6)),
    });
  }
}

/** Dispara una neurona: marca energía, registra el evento y propaga. */
export function fire(field: NeuralField, index: number, strength = 1): boolean {
  const neuron = field.neurons[index];
  if (!neuron || neuron.refractory > 0) return false;
  neuron.energy = Math.min(1.4, neuron.energy + strength);
  neuron.refractory = REFRACTORY_SECONDS;
  field.firings.push(field.time);
  spawnFrom(field, index, strength);
  return true;
}

/** Excita lo que está cerca del puntero: la red reacciona al moverse. */
export function excite(field: NeuralField, x: number, y: number, radius = 0.075): number {
  const radiusSq = radius * radius;
  let fired = 0;
  for (let i = 0; i < field.neurons.length && fired < 4; i += 1) {
    const neuron = field.neurons[i];
    if (neuron.refractory > 0) continue;
    const dx = neuron.x - x;
    const dy = neuron.y - y;
    if (dx * dx + dy * dy <= radiusSq && fire(field, i, 0.85)) fired += 1;
  }
  return fired;
}

/** Avanza la simulación `dt` segundos. */
export function stepNeuralField(field: NeuralField, dt: number): void {
  const step = Math.min(0.05, Math.max(0, dt));
  if (step === 0) return;
  field.time += step;

  for (const neuron of field.neurons) {
    neuron.energy = Math.max(0, neuron.energy - step * 1.5);
    if (neuron.refractory > 0) neuron.refractory = Math.max(0, neuron.refractory - step);
  }

  const survivors: Pulse[] = [];
  for (const pulse of field.pulses) {
    pulse.t += step * pulse.speed;
    if (pulse.t >= 1) {
      const target = otherEnd(field, pulse);
      fire(field, target, pulse.strength);
      continue;
    }
    survivors.push(pulse);
  }
  field.pulses = survivors;

  // Actividad espontánea: el cerebro nunca se apaga del todo.
  field.nextSpontaneousIn -= step;
  if (field.nextSpontaneousIn <= 0) {
    field.nextSpontaneousIn = 0.16 + field.random() * 0.5;
    const index = Math.floor(field.random() * field.neurons.length);
    fire(field, index, 0.9);
  }

  const cutoff = field.time - RATE_WINDOW_MS / 1000;
  while (field.firings.length && field.firings[0] < cutoff) field.firings.shift();
  field.rate = field.firings.length;
}

/** Cuántas sinapsis están conduciendo ahora (para la lectura en pantalla). */
export function activePulses(field: NeuralField): number {
  return field.pulses.length;
}
