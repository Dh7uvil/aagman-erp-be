"""Linked ERP document references on detail responses."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class RelatedDocumentRef(BaseModel):
    document_type: str
    document_id: UUID
    document_number: str
    status: str
    relationship: str
    document_date: str | None = None
    quantity_summary: str | None = None
    amount_summary: str | None = None

    model_config = {"from_attributes": True}
