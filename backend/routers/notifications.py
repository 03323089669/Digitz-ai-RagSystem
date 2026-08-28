from fastapi import APIRouter

from core.db import (
    get_notification_counts,
    get_notifications,
    mark_notification_read,
    mark_all_notifications_read,
)

router = APIRouter(prefix='/notifications', tags=['notifications'])


@router.get('/')
def list_notifications(limit: int = 12):
    return {'notifications': get_notifications(limit)}


@router.get('/counts')
def notification_counts():
    return get_notification_counts()


@router.patch('/{notification_id}/read')
def mark_read(notification_id: str):
    mark_notification_read(notification_id)
    return {'ok': True}


@router.patch('/read-all')
def mark_all_read():
    mark_all_notifications_read()
    return {'ok': True}
