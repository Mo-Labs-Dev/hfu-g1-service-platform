"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { ContactShadows, useGLTF } from "@react-three/drei";
import { Suspense, useEffect, useRef } from "react";
import * as THREE from "three";

function Robot() {
  const rotatingGroup = useRef<THREE.Group>(null);
  const { scene } = useGLTF("/models/g1.glb");

  useEffect(() => {
    scene.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;

      object.castShadow = true;
      object.receiveShadow = true;

      const name = object.name.toLowerCase();

      // Dark mechanical parts
      if (
        name.includes("hip") ||
        name.includes("knee") ||
        name.includes("ankle") ||
        name.includes("waist") ||
        name.includes("shoulder") ||
        name.includes("elbow") ||
        name.includes("wrist") ||
        name.includes("rubber_hand") ||
        name.includes("pelvis")
      ) {
        object.material = new THREE.MeshStandardMaterial({
          color: "#30363a",
          roughness: 0.42,
          metalness: 0.5,
        });
      }

      // Metallic body
      if (
        name.includes("torso") ||
        name.includes("upper") ||
        name.includes("lower")
      ) {
        object.material = new THREE.MeshStandardMaterial({
          color: "#b8bec2",
          roughness: 0.3,
          metalness: 0.6,
        });
      }

      // Head
      if (name.includes("head")) {
        object.material = new THREE.MeshStandardMaterial({
          color: "#343a3e",
          roughness: 0.35,
          metalness: 0.55,
        });
      }
    });
  }, [scene]);

  useFrame((_, delta) => {
    if (rotatingGroup.current) {
      // Slow continuous 360° rotation
      rotatingGroup.current.rotation.y += delta * 0.3;
    }
  });

  return (
    <group ref={rotatingGroup} position={[0, -0.78, 0]}>
      <group rotation={[-Math.PI / 2, 0, 0]}>
        <primitive object={scene} scale={1.25} />
      </group>
    </group>
  );
}

function BlueGroundGlow() {
  return (
    <mesh
      position={[0, -1.76, 0]}
      rotation={[-Math.PI / 2, 0, 0]}
    >
      <circleGeometry args={[0.72, 64]} />

      <meshBasicMaterial
        color="#0077ff"
        transparent
        opacity={0.10}
        depthWrite={false}
      />
    </mesh>
  );
}

export default function G1Model() {
  return (
    <div className="h-full w-full">
      <Canvas
        shadows
        camera={{
          position: [0, 0.15, 5],
          fov: 30,
        }}
        gl={{
          antialias: true,
          alpha: true,
        }}
        dpr={[1, 2]}
      >
        {/* Normal studio lighting */}
        <ambientLight intensity={1.15} />

        <directionalLight
          position={[4, 6, 5]}
          intensity={2.5}
          castShadow
        />

        <directionalLight
          position={[-4, 3, 4]}
          intensity={1.2}
        />

        <directionalLight
          position={[0, 4, -5]}
          intensity={0.8}
        />

        {/* BLUE UNDERGLOW */}

        <pointLight
          position={[-0.45, -1.25, 0.65]}
          color="#008cff"
          intensity={12}
          distance={3.5}
          decay={2}
        />

        <pointLight
          position={[0.45, -1.25, 0.65]}
          color="#008cff"
          intensity={12}
          distance={3.5}
          decay={2}
        />

        <pointLight
          position={[0, -0.75, -0.4]}
          color="#005eff"
          intensity={7}
          distance={3}
          decay={2}
        />

        <Suspense fallback={null}>
          <Robot />

          <BlueGroundGlow />

          <ContactShadows
            position={[0, -1.78, 0]}
            opacity={0.25}
            scale={2.3}
            blur={2.5}
            far={2}
          />
        </Suspense>
      </Canvas>
    </div>
  );
}

useGLTF.preload("/models/g1.glb");