"""Pydantic 模型。

Decimal 类型同时接受数字与字符串（推荐字符串，避免 JSON 数字经 float 解析），
输出统一为字符串以保留精度。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer, field_validator

# 输入：数字或字符串均可；输出：字符串
DecimalStr = Annotated[
    Decimal,
    PlainSerializer(lambda d: format(d, "f"), return_type=str, when_used="json"),
]


def _check_id(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("容器 ID 不能为空")
    return v


class SampleIn(BaseModel):
    sample_id: str = Field(..., min_length=1, description="初始样品（容器）ID")
    volume: DecimalStr = Field(..., description="初始体积，非负且小数位受限")

    @field_validator("sample_id")
    @classmethod
    def _id(cls, v: str) -> str:
        return _check_id(v)


class ContainerIn(BaseModel):
    container_id: str = Field(..., min_length=1, description="空容器 ID")

    @field_validator("container_id")
    @classmethod
    def _id(cls, v: str) -> str:
        return _check_id(v)


class TransferIn(BaseModel):
    source: str = Field(..., min_length=1, description="源容器 ID")
    destination: str = Field(..., min_length=1, description="目标容器 ID")
    volume: DecimalStr = Field(..., description="转移体积（> 0，不超过源容器当前体积）")

    @field_validator("source", "destination")
    @classmethod
    def _ids(cls, v: str) -> str:
        return _check_id(v)


class BatchTransferIn(BaseModel):
    transfers: list[TransferIn] = Field(
        ..., min_length=1, description="按数组顺序依次执行的转移"
    )


class SourceOut(BaseModel):
    source_id: str
    amount: DecimalStr = Field(..., description="该祖先来源在容器中的绝对体积")
    proportion: DecimalStr = Field(..., description="占当前体积的比例")


class ContainerStatusOut(BaseModel):
    container_id: str
    volume: DecimalStr
    sources: list[SourceOut]
    proportion_scale: int


class SampleOut(BaseModel):
    sample_id: str
    volume: DecimalStr


class ContainerOut(BaseModel):
    container_id: str


class BatchTransferOut(BaseModel):
    applied: int
    message: str
