"""Unit tests for the DDI stub (always returns empty list)."""

import uuid

import pytest

from app.modules.prescriptions.ddi_stub import check_drug_interactions


@pytest.mark.asyncio
async def test_returns_empty_list_with_no_medications():
    result = await check_drug_interactions(
        patient_id=uuid.uuid4(), atc_code="A01AA01", active_medications=[]
    )
    assert result == []


@pytest.mark.asyncio
async def test_returns_empty_list_with_one_medication():
    result = await check_drug_interactions(
        patient_id=uuid.uuid4(), atc_code="A01AA01", active_medications=["B01AA01"]
    )
    assert result == []


@pytest.mark.asyncio
async def test_returns_empty_list_with_many_medications():
    meds = [f"X{i:02d}AA01" for i in range(20)]
    result = await check_drug_interactions(
        patient_id=uuid.uuid4(), atc_code="C01AA01", active_medications=meds
    )
    assert result == []


@pytest.mark.asyncio
async def test_returns_list_type():
    result = await check_drug_interactions(
        patient_id=uuid.uuid4(), atc_code="D", active_medications=[]
    )
    assert isinstance(result, list)
