"""Pydantic request/response schemas with explicit, validated ranges."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ProjectCreate(BaseModel):
    name: str = Field(default="Untitled scene", min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name cannot be blank")
        return v


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    asset_order: list[str] | None = Field(default=None, max_length=1000)


class AdvancedSettings(BaseModel):
    """Every knob has a safe default; beginners never see these."""

    sample_fps: float = Field(default=4.0, ge=0.5, le=15)
    trim_start: float = Field(default=0.0, ge=0)
    trim_end: float | None = Field(default=None, ge=0)
    max_frames: int = Field(default=120, ge=8, le=300)
    exclude: list[str] = Field(default_factory=list, max_length=1000)
    drop_blurry: bool = True
    working_max_side: int = Field(default=1600, ge=640, le=3200)
    max_features: int = Field(default=6000, ge=1000, le=16000)
    matcher: Literal["auto", "exhaustive", "sequential"] = "auto"
    depth_max_side: int = Field(default=640, ge=256, le=1280)
    confidence_floor: float = Field(default=0.2, ge=0, le=0.9)
    outlier_std: float = Field(default=2.0, ge=0.5, le=5)
    mesh: bool = True
    mesh_resolution: int = Field(default=192, ge=64, le=320)
    splat_preset: Literal["performance", "balanced", "quality"] = "balanced"
    splat_iterations: int | None = Field(default=None, ge=500, le=60000)
    splat_trainer: Literal["msplat", "gsplat", "splatfacto"] | None = None


class JobCreate(BaseModel):
    mode: Literal["quick", "high"] = "quick"
    settings: AdvancedSettings = Field(default_factory=AdvancedSettings)


class EditOp(BaseModel):
    type: Literal["crop", "removePoints", "hideRegion", "rotate", "recenter", "alignGround", "scale",
                  "display", "cameraPreset", "scaleReference"]
    params: dict = Field(default_factory=dict)
    id: str | None = Field(default=None, max_length=64)


class EditsPut(BaseModel):
    version: int = 1
    ops: list[EditOp] = Field(default_factory=list, max_length=2000)
