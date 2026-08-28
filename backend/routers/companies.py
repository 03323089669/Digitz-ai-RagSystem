from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.db import get_brands, get_active_company, set_active_company, get_brand
from routers.auth import get_current_user

router = APIRouter(prefix='/companies', tags=['companies'])


class ActiveCompanyPayload(BaseModel):
    company_key: str


@router.get('/')
def list_companies():
    return {
        'companies': get_brands(),
        'active_company': get_active_company(),
    }


@router.post('/set-active-company')
def set_company(payload: ActiveCompanyPayload, current_user: dict = Depends(get_current_user)):
    company = get_brand(payload.company_key)
    if not company:
        raise HTTPException(status_code=404, detail='Company not found')

    set_active_company(payload.company_key)
    return {
        'active_company': payload.company_key,
        'company': company,
    }
