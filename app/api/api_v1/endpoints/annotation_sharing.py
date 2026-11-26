from fastapi import APIRouter, Depends, HTTPException, Body, status, Query as FQuery
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional, List
import json
import logging
import datetime
from app.api.deps import get_current_user
from app.persistence import AnnotationStorageService, SharedAnnotationStorageService
from app.constants import ROLES
import jwt
from uuid import uuid4
from app.api.annotation_id import AnnotationID, validate_annotation_id
from app.api.auth import get_share_signing_key

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/share")
def share_annotation(data: Dict[str, Any] = Body(...), current_user_id: str = Depends(get_current_user)):
    try:
        annotation_id = data.get('annotation_id', None)
        share_type = data.get('share_type', 'public')   # default is public
        recipient_user_id = data.get('recipient_user_id')  # only required for private
        role = data.get('role')
        
        if role not in ROLES:
            raise HTTPException(status_code=400, detail="Role should be viewer, owner or editor")
            

        annotation_id = validate_annotation_id(annotation_id)
        if share_type not in ("public", "private"):
            raise HTTPException(status_code=400, detail="Invalid share type")
        if share_type == "public" and role != "viewer":
            raise HTTPException(status_code=400, detail="Public shares are read-only")

        annotation = AnnotationStorageService.get_by_id(annotation_id)

        if not annotation:
            raise HTTPException(status_code=404, detail="Annotation not found")

        # Only the owner can share their own annotation
        if str(annotation.user_id) != str(current_user_id):
            raise HTTPException(status_code=404, detail="Annotation not found")

        # If private, recipient_user_id must be given
        if share_type == "private" and not recipient_user_id:
            raise HTTPException(status_code=400, detail="Missing recipient user ID for private share")

        # Check if already shared
        shared_resource = SharedAnnotationStorageService.get({
            'user_id': current_user_id,
            'annotation_id': annotation_id,
        })

        share = {
            "annotation_id": annotation_id,
            "share_type": share_type,
            "recipient_user_id": recipient_user_id,
            "role": role,
        }
        secret = get_share_signing_key()
        if shared_resource and all(
            getattr(shared_resource, key) == value for key, value in share.items()
        ):
            return {"user_id": current_user_id, **share, "token": shared_resource.token}

        token = jwt.encode(
            {"user_id": current_user_id, **share, "type": "annotation_share", "jti": uuid4().hex},
            secret,
            algorithm="HS256",
        )
        if shared_resource:
            SharedAnnotationStorageService.update(shared_resource.id, {**share, "token": token})
        else:
            annotation_share = SharedAnnotationStorageService.save({
                **share, "current_user_id": current_user_id, "token": token,
            })
            if not annotation_share:
                raise HTTPException(status_code=500, detail="Failed to save shared annotation")

        response = {
            'user_id': current_user_id,
            'annotation_id': annotation_id,
            'share_type': share_type,
            'recipient_user_id': recipient_user_id,
            'token': token,
            'role': role
        }

        return response
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error sharing annotation")
        raise HTTPException(status_code=500, detail="Could not share annotation") from None

@router.delete("/{id:annotation_id}")
def revoke_shared_annotation(id: AnnotationID, current_user_id: str = Depends(get_current_user)):
    try:
        # Get the annotation
        annotation = AnnotationStorageService.get_by_id(id)
        if annotation is None:
            raise HTTPException(status_code=404, detail="Annotation not found")

        # Only owner can revoke
        if str(annotation.user_id) != str(current_user_id):
            raise HTTPException(status_code=404, detail="Annotation not found")

        # Get the shared record
        shared_resource = SharedAnnotationStorageService.get({
            'user_id': current_user_id,
            'annotation_id': id,
        })

        if shared_resource is None:
            raise HTTPException(status_code=404, detail="No shared record found")

        # Delete the shared record
        SharedAnnotationStorageService.delete(shared_resource.id)

        return {'message': 'Annotation revoked successfully'}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Error revoking shared annotation")
        raise HTTPException(status_code=500, detail="Could not revoke annotation share") from None
