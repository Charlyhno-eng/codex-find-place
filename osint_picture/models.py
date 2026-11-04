from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(Strict):
    title: str
    url: str
    supports: str


class Clue(Strict):
    category: str
    observation: str
    interpretation: str
    strength: Literal["faible", "moyenne", "forte"]


class Coordinates(Strict):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float | None = Field(ge=0)
    altitude_meters: float | None = Field(default=None, description="Altitude above mean sea level in meters; null unless verified.")
    altitude_basis: str | None = None
    basis: str


class Candidate(Strict):
    visual_similarity_score: float | None = Field(default=None, ge=0, le=100)
    similarity_basis: str | None = None
    place: str
    country: str | None
    city: str | None
    timezone: str | None
    coordinates: Coordinates | None
    confidence: Literal["faible", "moyenne", "forte"]
    supporting_evidence: list[str]
    contradictions: list[str]
    sources: list[Source]


class Provenance(Strict):
    ai_assessment: Literal["indéterminée", "indices de génération", "provenance déclarée"]
    ai_evidence: list[str]
    author: str | None
    author_basis: str
    limitations: list[str]


class MapZone(Strict):
    label: str
    south: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    confidence: Literal["faible", "moyenne", "forte"]
    basis: str

    @model_validator(mode="after")
    def valid_bounds(self):
        if self.south >= self.north or self.west >= self.east:
            raise ValueError("Zone vide ou inversée ; scinder les zones traversant l'antiméridien")
        return self


class VisualComparison(Strict):
    reference_id: str
    verdict: Literal["correspondance", "compatible", "écartée", "non exploitable"]
    matching_details: list[str]
    differences: list[str]
    conclusion: str


class TestedPlace(Strict):
    label: str
    status: Literal["à vérifier", "compatible", "écarté", "accès bloqué"]
    latitude: float | None = Field(ge=-90, le=90)
    longitude: float | None = Field(ge=-180, le=180)
    basis: str
    sources: list[Source]
    street_view_heading: float | None = Field(ge=0, lt=360)

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude et longitude doivent être renseignées ensemble")
        return self


class CameraOrientation(Strict):
    heading_degrees: float | None = Field(default=None, ge=0, lt=360,
        description="Camera viewing azimuth clockwise from true north; null when unknown.")
    pitch_degrees: float | None = Field(default=None, ge=-90, le=90,
        description="Camera elevation above the horizon; negative means looking down.")
    uncertainty_degrees: float | None = Field(default=None, ge=0, le=180)
    basis: str = "Camera orientation could not be established."


class Report(Strict):
    continue_research: bool = Field(default=False, description="Continue only when concrete, untested checks can improve localization. False when blocked or exhausted.")
    next_check: str = ""
    summary: str
    conclusion: str
    precision: Literal["indéterminée", "pays", "région", "ville", "site", "coordonnées"]
    best_candidate: Candidate | None
    alternatives: list[Candidate]
    clues: list[Clue]
    visible_text: list[str]
    provenance: Provenance
    temporal_analysis: str
    research_performed: list[str]
    limitations: list[str]
    sources: list[Source]
    localization_confirmed: bool = Field(default=False,
        description="True only when the photographed site or camera position is identified with decisive, verifiable evidence, not regional compatibility.")
    camera_orientation: CameraOrientation | None = None

    map_zones: list[MapZone] = Field(default_factory=list, max_length=8)
    reference_queries: list[str] = Field(default_factory=list, max_length=4)
    visual_comparisons: list[VisualComparison] = Field(default_factory=list)
    tested_places: list[TestedPlace] = Field(default_factory=list, max_length=24)
    narrowing: str = ""
