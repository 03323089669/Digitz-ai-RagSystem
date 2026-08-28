from fastapi import APIRouter, Depends, Query
from core.db import get_conn
from routers.auth import get_current_user

router = APIRouter(prefix='/admin', tags=['admin'])


@router.get('/queries')
def list_queries(
    brand: str | None = Query(None),
    keyword: str | None = Query(None),
    date: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    if current_user['role'] != 'admin':
        raise PermissionError('Admin access required')

    with get_conn() as conn:
        sql = 'SELECT * FROM queries WHERE 1=1'
        params = []
        if brand:
            sql += ' AND brand_key = ?'
            params.append(brand)
        if keyword:
            sql += ' AND query_text LIKE ?'
            params.append(f'%{keyword}%')
        if date:
            sql += ' AND created_at LIKE ?'
            params.append(f'%{date}%')
        sql += ' ORDER BY created_at DESC'
        rows = conn.execute(sql, tuple(params)).fetchall()
        return {'queries': [dict(row) for row in rows]}
