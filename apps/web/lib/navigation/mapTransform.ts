export type Point2D = {
  x: number;
  y: number;
};

export type Point3D = {
  x: number;
  y: number;
  z: number;
};

// Estimated HFU Session 03 floor plane.
// These values are not a calibrated ROS TF.
const A = 0.08143;
const B = 0.02414;
const C = -1.22643;

function normalize(
  vector: [number, number, number]
): [number, number, number] {
  const length = Math.hypot(...vector);

  return [
    vector[0] / length,
    vector[1] / length,
    vector[2] / length,
  ];
}

function cross(
  a: [number, number, number],
  b: [number, number, number]
): [number, number, number] {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

const normal = normalize([-A, -B, 1]);
const ex = normalize([1, 0, A]);
const ey = cross(normal, ex);

export function leveledToRaw(
  point: Point3D
): Point3D {
  return {
    x:
      point.x * ex[0] +
      point.y * ey[0] +
      point.z * normal[0],
    y:
      point.x * ex[1] +
      point.y * ey[1] +
      point.z * normal[1],
    z:
      C +
      point.x * ex[2] +
      point.y * ey[2] +
      point.z * normal[2],
  };
}

// Convert ROS/FAST-LIO coordinates into the
// Three.js orientation used by HfuLabMap3D.
export function rawToThree(
  raw: Point3D,
  center: Point3D
): [number, number, number] {
  return [
    raw.x - center.x,
    raw.z - center.z,
    -(raw.y - center.y),
  ];
}

export function destinationToThree(
  destination: Point2D,
  center: Point3D,
  height = 0
): [number, number, number] {
  const raw = leveledToRaw({
    x: destination.x,
    y: destination.y,
    z: height,
  });

  return rawToThree(raw, center);
}