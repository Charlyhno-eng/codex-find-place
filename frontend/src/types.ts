export interface Source {
  title: string;
  url: string;
  supports: string;
}
export interface Coordinates {
  kind?: "camera" | "landmark" | "area" | "unknown";
  latitude: number;
  longitude: number;
  accuracy_meters: number | null;
  altitude_meters?: number | null;
  altitude_basis?: string | null;
  basis: string;
}
export interface Candidate {
  place: string;
  city: string | null;
  country: string | null;
  confidence: string;
  coordinates: Coordinates | null;
  supporting_evidence: string[];
  contradictions: string[];
  sources: Source[];
  visual_similarity_score?: number | null;
  similarity_basis?: string | null;
}
export interface Report {
  summary: string;
  conclusion: string;
  precision: string;
  localization_confirmed: boolean;
  best_candidate: Candidate | null;
  alternatives: Candidate[];
  clues: {
    category: string;
    strength: string;
    observation: string;
    interpretation: string;
  }[];
  visual_comparisons?: {
    reference_id: string;
    verdict: string;
    conclusion: string;
    matching_details: string[];
    differences: string[];
  }[];
  visible_text: string[];
  temporal_analysis: string;
  limitations: string[];
  sources: Source[];
  research_performed: string[];
  provenance: {
    ai_assessment: string;
    ai_evidence: string[];
    author: string | null;
    author_basis: string;
    limitations: string[];
  };
  camera_orientation?: {
    heading_degrees: number | null;
    pitch_degrees: number | null;
    uncertainty_degrees: number | null;
    basis: string;
  } | null;
  narrowing?: string;
  map_zones?: {
    label: string;
    south: number;
    west: number;
    north: number;
    east: number;
    confidence: string;
    basis: string;
  }[];
  tested_places?: {
    label: string;
    status: string;
    latitude: number | null;
    longitude: number | null;
    basis: string;
  }[];
}
export interface Settings {
  model: string;
  reasoning_effort: string;
}
export interface Catalog {
  settings: Settings;
  models: { id: string; name: string; efforts: string[] }[];
}
export interface Revision {
  stage: string;
  time?: string;
  report: Report;
}
export interface JobSummary {
  id: string;
  filename: string;
  status: string;
  created_at: string;
}
export interface Job extends JobSummary {
  stage: string;
  progress: number;
  events: { time: string; message: string }[];
  error: string | null;
  settings: Settings | null;
  report: Report | null;
  partial: Report | null;
  metadata:
    | ({ width: number; height: number; bytes: number } & Record<
        string,
        unknown
      >)
    | null;
  solar: unknown;
  revisions: Revision[];
  references: {
    id: string;
    title: string;
    page_url: string;
    license_url: string;
    author: string;
    license: string;
    query: string;
  }[];
  reference_batches: { stage: string; errors?: string[] }[];
}
