import numpy as np

# Estimated floor plane in raw FAST-LIO coordinates:
# z = A*x + B*y + C

A = 0.08143
B = 0.02414
C = -1.22643

# Define the leveled coordinate axes.
normal = np.array([-A, -B, 1.0])
normal = normal / np.linalg.norm(normal)

ex = np.array([1.0, 0.0, A])
ex = ex / np.linalg.norm(ex)

ey = np.cross(normal, ex)

# Raw FAST-LIO origin projected onto the estimated floor.
floor_origin = np.array([0.0, 0.0, C])


def raw_to_leveled(point):
    point = np.asarray(point, dtype=float)
    relative = point - floor_origin

    return np.array([
        np.dot(relative, ex),
        np.dot(relative, ey),
        np.dot(relative, normal),
    ])


def leveled_to_raw(point):
    point = np.asarray(point, dtype=float)

    return (
        floor_origin
        + point[0] * ex
        + point[1] * ey
        + point[2] * normal
    )


def main():
    print("=== HFU MAP COORDINATE ALIGNMENT ===")

    print("\nEstimated floor origin:", floor_origin)
    print("Leveled X axis:", ex)
    print("Leveled Y axis:", ey)
    print("Leveled Z axis:", normal)

    locations = {
        "Recorded start": [0.0966, 0.0190, 0.0],
        "Coffee landmark": [0.6000, 8.0000, 0.0],
    }

    for name, leveled_point in locations.items():
        raw = leveled_to_raw(leveled_point)
        recovered = raw_to_leveled(raw)

        print(f"\n{name}")
        print("  Leveled:", np.round(leveled_point, 4))
        print("  Raw FAST-LIO:", np.round(raw, 4))
        print("  Round-trip:", np.round(recovered, 4))

        error = np.linalg.norm(
            np.asarray(leveled_point) - recovered
        )

        print("  Round-trip error:", round(error, 8))

    print("\nRotation matrix (leveled -> raw):")
    rotation = np.column_stack([ex, ey, normal])
    print(np.round(rotation, 6))

    print("\nNOTE:")
    print("This is an estimated visualization transform.")
    print("Round-trip accuracy does not prove physical alignment.")
    print("No robot movement is authorized.")


if __name__ == "__main__":
    main()
    