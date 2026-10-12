"use client";

import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

type LocationType =
  | "home"
  | "navigation"
  | "workstation"
  | "interaction";

type RobotLocation = {
  id: string;
  name: string;
  target: string;
  description: string;
  type: LocationType;
  x: number | null;
  y: number | null;
  yaw: number | null;
  configured: boolean;
};

type RobotStatus = {
  current_location?: string;
};

type NewLocationForm = {
  name: string;
  target: string;
  description: string;
  type: LocationType;
};

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

const EMPTY_FORM: NewLocationForm = {
  name: "",
  target: "",
  description: "",
  type: "navigation",
};

export default function LocationsPage() {
  const [locations, setLocations] = useState<
    RobotLocation[]
  >([]);

  const [selectedLocation, setSelectedLocation] =
    useState<RobotLocation | null>(null);

  const [robotLocation, setRobotLocation] =
    useState<string | null>(null);

  const [backendOnline, setBackendOnline] =
    useState(false);

  const [loading, setLoading] = useState(true);

  const [error, setError] = useState<string | null>(
    null
  );

  const [showAddLocation, setShowAddLocation] =
    useState(false);

  const [saving, setSaving] = useState(false);

  const [newLocation, setNewLocation] =
    useState<NewLocationForm>(EMPTY_FORM);

  /* ========================================================
     LOAD LOCATIONS
  ======================================================== */

  const loadLocations = useCallback(async () => {
    try {
      const response = await fetch(
        `${API_URL}/api/locations`,
        {
          cache: "no-store",
        }
      );

      if (!response.ok) {
        throw new Error(
          `Locations API returned ${response.status}`
        );
      }

      const data: RobotLocation[] =
        await response.json();

      setLocations(data);
      setBackendOnline(true);
      setError(null);

      setSelectedLocation((current) => {
        if (!current) {
          return null;
        }

        return (
          data.find(
            (location) =>
              location.id === current.id
          ) || null
        );
      });
    } catch (requestError) {
      console.error(
        "Unable to load locations:",
        requestError
      );

      setBackendOnline(false);

      setError(
        "Unable to connect to the Locations API."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  /* ========================================================
     LOAD ROBOT STATUS
  ======================================================== */

  const loadRobotStatus = useCallback(async () => {
    try {
      const response = await fetch(
        `${API_URL}/api/robot/status`,
        {
          cache: "no-store",
        }
      );

      if (!response.ok) {
        throw new Error(
          `Robot API returned ${response.status}`
        );
      }

      const data: RobotStatus =
        await response.json();

      setRobotLocation(
        data.current_location || null
      );
    } catch (requestError) {
      console.error(
        "Unable to load robot status:",
        requestError
      );
    }
  }, []);

  /* ========================================================
     INITIAL LOAD
  ======================================================== */

  useEffect(() => {
    void loadLocations();
    void loadRobotStatus();

    const interval = window.setInterval(() => {
      void loadRobotStatus();
    }, 5000);

    return () => {
      window.clearInterval(interval);
    };
  }, [loadLocations, loadRobotStatus]);

  /* ========================================================
     CREATE LOCATION
  ======================================================== */

  async function handleCreateLocation(
    event: FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    if (
      !newLocation.name.trim() ||
      !newLocation.target.trim()
    ) {
      setError(
        "Location name and target are required."
      );

      return;
    }

    setSaving(true);
    setError(null);

    try {
      const response = await fetch(
        `${API_URL}/api/locations`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: newLocation.name.trim(),
            target: newLocation.target.trim(),
            description:
              newLocation.description.trim(),
            type: newLocation.type,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            "Unable to create location."
        );
      }

      const createdLocation =
        data as RobotLocation;

      setNewLocation(EMPTY_FORM);
      setShowAddLocation(false);

      await loadLocations();

      setSelectedLocation(createdLocation);
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Unable to create location.";

      setError(message);
    } finally {
      setSaving(false);
    }
  }

  /* ========================================================
     CLEAR CALIBRATION
  ======================================================== */

  async function clearCalibration() {
    if (!selectedLocation) {
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const response = await fetch(
        `${API_URL}/api/locations/${selectedLocation.id}/calibration`,
        {
          method: "DELETE",
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            "Unable to clear calibration."
        );
      }

      setSelectedLocation(
        data as RobotLocation
      );

      await loadLocations();
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Unable to clear calibration.";

      setError(message);
    } finally {
      setSaving(false);
    }
  }

  /* ========================================================
     DELETE LOCATION
  ======================================================== */

  async function deleteSelectedLocation() {
    if (!selectedLocation) {
      return;
    }

    const confirmed = window.confirm(
      `Delete "${selectedLocation.name}"?`
    );

    if (!confirmed) {
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const response = await fetch(
        `${API_URL}/api/locations/${selectedLocation.id}`,
        {
          method: "DELETE",
        }
      );

      if (!response.ok) {
        let message =
          "Unable to delete location.";

        try {
          const data = await response.json();

          if (data.detail) {
            message = data.detail;
          }
        } catch {
          // No JSON response body.
        }

        throw new Error(message);
      }

      setSelectedLocation(null);

      await loadLocations();
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Unable to delete location.";

      setError(message);
    } finally {
      setSaving(false);
    }
  }

  /* ========================================================
     COUNTERS
  ======================================================== */

  const configuredCount = useMemo(
    () =>
      locations.filter(
        (location) => location.configured
      ).length,
    [locations]
  );

  const pendingCount =
    locations.length - configuredCount;

  /* ========================================================
     PAGE
  ======================================================== */

  return (
    <div className="min-h-[calc(100vh-88px)] bg-[#f7f8f7]">
      {/* ================================================= */}
      {/* PAGE HEADER */}
      {/* ================================================= */}

      <section className="border-b border-[#e0e3e1] bg-white">
        <div className="mx-auto max-w-[1600px] px-16 py-12">
          <div className="flex items-end justify-between">
            <div>
              <div className="h-[3px] w-12 bg-[#009b77]" />

              <p className="mt-6 text-[10px] font-bold uppercase tracking-[0.22em] text-[#8a9499]">
                Navigation Engineering
              </p>

              <h1 className="mt-4 text-[40px] font-bold tracking-[-0.04em] text-[#2d3337]">
                Locations
              </h1>

              <p className="mt-4 max-w-[650px] text-[14px] leading-6 text-[#707b81]">
                Define reusable semantic navigation
                targets for G1 guidance, assistance
                and demonstration workflows.
              </p>
            </div>

            <div className="flex items-center gap-7 pb-1">
              <div className="flex items-center gap-3">
                <span
                  className={`h-2 w-2 rounded-full ${
                    backendOnline
                      ? "bg-[#009b77]"
                      : "bg-[#b7bdc0]"
                  }`}
                />

                <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-[#747f84]">
                  {backendOnline
                    ? "Location API Online"
                    : "Location API Offline"}
                </span>
              </div>

              <button
                type="button"
                onClick={() =>
                  setShowAddLocation(true)
                }
                className="flex h-[44px] items-center gap-4 bg-[#009b77] px-6 text-[10px] font-bold uppercase tracking-[0.15em] text-white transition-colors hover:bg-[#00866a]"
              >
                <span className="text-[17px] font-light">
                  +
                </span>

                Add Location
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* ================================================= */}
      {/* WORKSPACE */}
      {/* ================================================= */}

      <section className="mx-auto max-w-[1600px] px-16 py-10">
        {error && (
          <div className="mb-6 flex items-center justify-between border border-[#ead7d7] bg-[#fffafa] px-5 py-4">
            <p className="text-[10px] font-semibold text-[#9a5d5d]">
              {error}
            </p>

            <button
              type="button"
              onClick={() => setError(null)}
              className="text-[9px] font-bold uppercase tracking-[0.12em] text-[#8c969a]"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* SUMMARY */}

        <div className="mb-8 grid grid-cols-3 gap-5">
          <SummaryCard
            label="Defined Locations"
            value={locations.length}
            description="Semantic navigation targets"
          />

          <SummaryCard
            label="Calibrated"
            value={configuredCount}
            description="Locations with robot coordinates"
          />

          <SummaryCard
            label="Calibration Required"
            value={pendingCount}
            description="Waiting for physical lab setup"
          />
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_360px] gap-7">
          {/* ============================================= */}
          {/* LOCATION LIBRARY */}
          {/* ============================================= */}

          <div className="border border-[#dfe3e1] bg-white">
            <div className="flex items-center justify-between border-b border-[#e5e8e6] px-7 py-6">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#657078]">
                  Lab Environment
                </p>

                <p className="mt-2 text-[9px] text-[#9aa2a6]">
                  Backend-managed robot navigation
                  targets
                </p>
              </div>

              <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-[#929b9f]">
                {locations.length} Locations
              </span>
            </div>

            {loading ? (
              <div className="flex min-h-[400px] items-center justify-center">
                <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-[#939da1]">
                  Loading Locations...
                </p>
              </div>
            ) : locations.length === 0 ? (
              <div className="flex min-h-[400px] items-center justify-center px-10">
                <div className="text-center">
                  <p className="text-[14px] font-bold text-[#566167]">
                    No locations defined
                  </p>

                  <p className="mt-3 text-[10px] leading-5 text-[#929ca0]">
                    Create the first semantic
                    navigation target for the robot.
                  </p>
                </div>
              </div>
            ) : (
              <div>
                {locations.map(
                  (location, index) => {
                    const current =
                      robotLocation ===
                        location.target ||
                      robotLocation ===
                        location.id;

                    const selected =
                      selectedLocation?.id ===
                      location.id;

                    return (
                      <button
                        key={location.id}
                        type="button"
                        onClick={() =>
                          setSelectedLocation(
                            location
                          )
                        }
                        className={`group flex w-full items-center border-b border-[#edf0ee] px-7 py-6 text-left transition-colors last:border-b-0 ${
                          selected
                            ? "bg-[#f5faf8]"
                            : "hover:bg-[#fafbfa]"
                        }`}
                      >
                        <div className="w-[55px] shrink-0">
                          <span className="text-[9px] font-bold tracking-[0.15em] text-[#b0b7ba]">
                            {String(
                              index + 1
                            ).padStart(2, "0")}
                          </span>
                        </div>

                        <div className="mr-5 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#dce1de] bg-[#fafbfa]">
                          <span
                            className={`h-2 w-2 rounded-full ${
                              current
                                ? "bg-[#009b77]"
                                : location.configured
                                  ? "bg-[#70aa9b]"
                                  : "bg-[#b9c0c3]"
                            }`}
                          />
                        </div>

                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-4">
                            <h2 className="text-[14px] font-bold text-[#414a4f]">
                              {location.name}
                            </h2>

                            {current && (
                              <span className="bg-[#eef8f5] px-2 py-1 text-[7px] font-bold uppercase tracking-[0.13em] text-[#00866a]">
                                Robot Here
                              </span>
                            )}
                          </div>

                          <p className="mt-2 max-w-[650px] text-[10px] leading-5 text-[#8d979b]">
                            {location.description ||
                              "No description"}
                          </p>
                        </div>

                        <div className="w-[190px] shrink-0">
                          <p className="text-[8px] font-bold uppercase tracking-[0.13em] text-[#a0a8ac]">
                            Target
                          </p>

                          <p className="mt-2 font-mono text-[10px] text-[#606b70]">
                            {location.target}
                          </p>
                        </div>

                        <div className="w-[150px] shrink-0">
                          <p className="text-[8px] font-bold uppercase tracking-[0.13em] text-[#a0a8ac]">
                            Calibration
                          </p>

                          <div className="mt-2 flex items-center gap-2">
                            <span
                              className={`h-1.5 w-1.5 rounded-full ${
                                location.configured
                                  ? "bg-[#009b77]"
                                  : "bg-[#b7bdc0]"
                              }`}
                            />

                            <span className="text-[9px] font-semibold text-[#68747a]">
                              {location.configured
                                ? "Configured"
                                : "Required"}
                            </span>
                          </div>
                        </div>

                        <div className="w-[35px] text-right">
                          <span className="text-[15px] text-[#a5adaf] transition-all group-hover:translate-x-1 group-hover:text-[#009b77]">
                            →
                          </span>
                        </div>
                      </button>
                    );
                  }
                )}
              </div>
            )}
          </div>

          {/* ============================================= */}
          {/* INSPECTOR */}
          {/* ============================================= */}

          <aside>
            <div className="sticky top-[118px] border border-[#dfe3e1] bg-white">
              <div className="border-b border-[#e5e8e6] px-6 py-6">
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#657078]">
                  Location Inspector
                </p>

                <p className="mt-2 text-[9px] text-[#9aa2a6]">
                  Navigation target configuration
                </p>
              </div>

              {!selectedLocation ? (
                <div className="flex min-h-[400px] items-center justify-center px-7">
                  <div className="text-center">
                    <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-[#dce1de]">
                      <span className="h-2 w-2 rounded-full bg-[#b7bdc0]" />
                    </div>

                    <p className="mt-6 text-[13px] font-semibold text-[#5a656a]">
                      Select a location
                    </p>

                    <p className="mt-2 text-[10px] leading-5 text-[#959da1]">
                      Choose a navigation target
                      from the lab environment.
                    </p>
                  </div>
                </div>
              ) : (
                <div className="px-6 py-6">
                  <p className="text-[8px] font-bold uppercase tracking-[0.14em] text-[#9aa2a6]">
                    Selected Location
                  </p>

                  <h2 className="mt-3 text-[18px] font-bold tracking-[-0.02em] text-[#3e484d]">
                    {selectedLocation.name}
                  </h2>

                  <p className="mt-3 text-[10px] leading-5 text-[#8b959a]">
                    {selectedLocation.description ||
                      "No description"}
                  </p>

                  <InspectorRow
                    label="Target ID"
                    value={selectedLocation.target}
                    mono
                  />

                  <InspectorRow
                    label="Location Type"
                    value={formatType(
                      selectedLocation.type
                    )}
                  />

                  <InspectorRow
                    label="Position X"
                    value={formatCoordinate(
                      selectedLocation.x
                    )}
                  />

                  <InspectorRow
                    label="Position Y"
                    value={formatCoordinate(
                      selectedLocation.y
                    )}
                  />

                  <InspectorRow
                    label="Orientation"
                    value={
                      selectedLocation.yaw === null
                        ? "Not calibrated"
                        : `${selectedLocation.yaw.toFixed(
                            2
                          )}°`
                    }
                  />

                  <div className="border-t border-[#edf0ee] py-5">
                    <div className="flex items-center justify-between">
                      <span className="text-[9px] font-bold uppercase tracking-[0.13em] text-[#8b959a]">
                        Calibration
                      </span>

                      <div className="flex items-center gap-2">
                        <span
                          className={`h-2 w-2 rounded-full ${
                            selectedLocation.configured
                              ? "bg-[#009b77]"
                              : "bg-[#b7bdc0]"
                          }`}
                        />

                        <span className="text-[9px] font-semibold text-[#5f6a6f]">
                          {selectedLocation.configured
                            ? "Configured"
                            : "Required"}
                        </span>
                      </div>
                    </div>
                  </div>

                  <button
                    type="button"
                    disabled={saving}
                    className="mt-3 flex h-[46px] w-full items-center justify-center bg-[#009b77] text-[9px] font-bold uppercase tracking-[0.15em] text-white transition-colors hover:bg-[#00866a] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Configure Location
                  </button>

                  {selectedLocation.configured && (
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() =>
                        void clearCalibration()
                      }
                      className="mt-3 flex h-[42px] w-full items-center justify-center border border-[#d9dfdc] bg-white text-[8px] font-bold uppercase tracking-[0.14em] text-[#68747a] transition-colors hover:bg-[#f7f8f7] disabled:opacity-50"
                    >
                      Clear Calibration
                    </button>
                  )}

                  <button
                    type="button"
                    disabled={saving}
                    onClick={() =>
                      void deleteSelectedLocation()
                    }
                    className="mt-3 flex h-[42px] w-full items-center justify-center border border-[#eadede] bg-white text-[8px] font-bold uppercase tracking-[0.14em] text-[#a06868] transition-colors hover:bg-[#fffafa] disabled:opacity-50"
                  >
                    Delete Location
                  </button>

                  <div className="mt-4 border border-[#e4e8e6] bg-[#fafbfa] px-4 py-4">
                    <p className="text-[8px] leading-4 text-[#929b9f]">
                      Physical coordinates will be
                      recorded during G1 navigation
                      calibration in the HFU
                      laboratory.
                    </p>
                  </div>
                </div>
              )}
            </div>
          </aside>
        </div>
      </section>

      {/* ================================================= */}
      {/* ADD LOCATION MODAL */}
      {/* ================================================= */}

      {showAddLocation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/25 px-6">
          <div className="w-full max-w-[560px] border border-[#dce1de] bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#e6e9e7] px-7 py-6">
              <div>
                <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-[#009b77]">
                  Navigation Engineering
                </p>

                <h2 className="mt-2 text-[22px] font-bold text-[#343c40]">
                  Add Location
                </h2>
              </div>

              <button
                type="button"
                onClick={() => {
                  setShowAddLocation(false);
                  setNewLocation(EMPTY_FORM);
                }}
                className="flex h-9 w-9 items-center justify-center border border-[#e0e4e2] text-[16px] text-[#778187] hover:bg-[#f7f8f7]"
              >
                ×
              </button>
            </div>

            <form
              onSubmit={handleCreateLocation}
              className="px-7 py-7"
            >
              <FormField label="Location Name">
                <input
                  required
                  value={newLocation.name}
                  onChange={(event) =>
                    setNewLocation(
                      (current) => ({
                        ...current,
                        name: event.target.value,
                      })
                    )
                  }
                  placeholder="Example: Reception"
                  className="h-11 w-full border border-[#dce1de] bg-white px-4 text-[11px] text-[#4d585d] outline-none transition-colors focus:border-[#009b77]"
                />
              </FormField>

              <FormField label="Semantic Target">
                <input
                  required
                  value={newLocation.target}
                  onChange={(event) =>
                    setNewLocation(
                      (current) => ({
                        ...current,
                        target:
                          event.target.value,
                      })
                    )
                  }
                  placeholder="Example: reception"
                  className="h-11 w-full border border-[#dce1de] bg-white px-4 font-mono text-[11px] text-[#4d585d] outline-none transition-colors focus:border-[#009b77]"
                />

                <p className="mt-2 text-[8px] leading-4 text-[#9aa2a6]">
                  Workflows will reference this
                  semantic target instead of physical
                  coordinates.
                </p>
              </FormField>

              <FormField label="Location Type">
                <select
                  value={newLocation.type}
                  onChange={(event) =>
                    setNewLocation(
                      (current) => ({
                        ...current,
                        type: event.target
                          .value as LocationType,
                      })
                    )
                  }
                  className="h-11 w-full border border-[#dce1de] bg-white px-4 text-[11px] text-[#4d585d] outline-none focus:border-[#009b77]"
                >
                  <option value="navigation">
                    Navigation
                  </option>

                  <option value="workstation">
                    Workstation
                  </option>

                  <option value="interaction">
                    Interaction
                  </option>

                  <option value="home">
                    Home
                  </option>
                </select>
              </FormField>

              <FormField label="Description">
                <textarea
                  value={newLocation.description}
                  onChange={(event) =>
                    setNewLocation(
                      (current) => ({
                        ...current,
                        description:
                          event.target.value,
                      })
                    )
                  }
                  placeholder="Describe how this location is used..."
                  rows={4}
                  className="w-full resize-none border border-[#dce1de] bg-white px-4 py-3 text-[11px] leading-5 text-[#4d585d] outline-none transition-colors focus:border-[#009b77]"
                />
              </FormField>

              <div className="mt-8 flex justify-end gap-3">
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => {
                    setShowAddLocation(false);
                    setNewLocation(EMPTY_FORM);
                  }}
                  className="h-11 border border-[#dce1de] px-6 text-[9px] font-bold uppercase tracking-[0.14em] text-[#707b80] hover:bg-[#f7f8f7]"
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  disabled={saving}
                  className="h-11 bg-[#009b77] px-7 text-[9px] font-bold uppercase tracking-[0.14em] text-white hover:bg-[#00866a] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {saving
                    ? "Creating..."
                    : "Create Location"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

/* =========================================================
   FORM FIELD
========================================================= */

function FormField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-6">
      <label className="mb-2 block text-[8px] font-bold uppercase tracking-[0.14em] text-[#7d888d]">
        {label}
      </label>

      {children}
    </div>
  );
}

/* =========================================================
   SUMMARY CARD
========================================================= */

function SummaryCard({
  label,
  value,
  description,
}: {
  label: string;
  value: number;
  description: string;
}) {
  return (
    <div className="border border-[#dfe3e1] bg-white px-6 py-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[8px] font-bold uppercase tracking-[0.15em] text-[#8d979c]">
            {label}
          </p>

          <p className="mt-3 text-[25px] font-bold tracking-[-0.03em] text-[#3e474c]">
            {value}
          </p>

          <p className="mt-2 text-[9px] text-[#9ba3a7]">
            {description}
          </p>
        </div>

        <div className="flex h-10 w-10 items-center justify-center rounded-full border border-[#dce1de] bg-[#fafbfa]">
          <span className="h-2 w-2 rounded-full bg-[#009b77]" />
        </div>
      </div>
    </div>
  );
}

/* =========================================================
   INSPECTOR ROW
========================================================= */

function InspectorRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between border-t border-[#edf0ee] py-5">
      <span className="text-[9px] font-bold uppercase tracking-[0.13em] text-[#8b959a]">
        {label}
      </span>

      <span
        className={`max-w-[170px] text-right text-[10px] font-semibold text-[#586368] ${
          mono ? "font-mono" : ""
        }`}
      >
        {value}
      </span>
    </div>
  );
}

/* =========================================================
   HELPERS
========================================================= */

function formatCoordinate(
  value: number | null
) {
  if (value === null) {
    return "Not calibrated";
  }

  return `${value.toFixed(2)} m`;
}

function formatType(type: LocationType) {
  switch (type) {
    case "home":
      return "Home";

    case "navigation":
      return "Navigation";

    case "workstation":
      return "Workstation";

    case "interaction":
      return "Interaction";

    default:
      return type;
  }
}