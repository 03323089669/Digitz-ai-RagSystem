from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.db import add_campaign, get_campaigns

router = APIRouter(prefix='/campaigns', tags=['campaigns'])


class CampaignPayload(BaseModel):
    name: str
    brand_key: str
    objective: str
    target_audience: str
    budget: float
    timeline: str
    status: str = 'Draft'


@router.post('/')
def create_campaign(payload: CampaignPayload):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail='Campaign name is required')
    campaign = add_campaign(
        payload.name,
        payload.brand_key,
        payload.objective,
        payload.target_audience,
        payload.budget,
        payload.timeline,
        payload.status,
    )
    return {'campaign': campaign}


@router.get('/')
def list_campaigns():
    return {'campaigns': get_campaigns()}
