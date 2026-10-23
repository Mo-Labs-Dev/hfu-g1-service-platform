export type GuidanceState =
  | "idle"
  | "preparing"
  | "departing"
  | "navigating"
  | "arriving"
  | "completed"
  | "cancelled"
  | "failed";

export type GuidanceStepStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type GuidanceStep = {
  id: string;
  name: string;
  action: string;
  status: GuidanceStepStatus;
};

export type GuidanceStatus = {
  session_id: string | null;
  destination: string | null;
  destination_name: string | null;
  mode: "simulation";
  state: GuidanceState;
  progress: number;
  message: string;
  active: boolean;
  started_at: string | null;
  updated_at: string;
  completed_at: string | null;
  physical_motion_requested: boolean;
  workflow_id: string;
  steps: GuidanceStep[];
};