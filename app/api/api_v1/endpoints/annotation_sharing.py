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
import os

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
            

        if not annotation_id:
            raise HTTPException(status_code=400, detail="Missing annotation ID")

        annotation = AnnotationStorageService.get_by_id(annotation_id)

        if not annotation:
            raise HTTPException(status_code=404, detail="Annotation not found")

        # If private, recipient_user_id must be given
        if share_type == "private" and not recipient_user_id:
            raise HTTPException(status_code=400, detail="Missing recipient user ID for private share")

        # Check if already shared
        shared_resource = SharedAnnotationStorageService.get({
            'user_id': current_user_id,
            'annotation_id': annotation_id,
        })

        if shared_resource:
            new_shared_resouce = SharedAnnotationStorageService.update(shared_resource.id, {
                'annotation_id': annotation_id,
                'share_type': share_type,
                'recipient_user_id': recipient_user_id,
                'token': shared_resource.token,
                'role': role
            })
            response = {
                'user_id': current_user_id,
                'annotation_id': annotation_id,
                'share_type': share_type,
                'recipient_user_id': recipient_user_id,
                'token': shared_resource.token,
                'role': role
            }

            return response

        # JWT Secret Key
        SHARED_TOKEN_SECRET = os.getenv("SHARED_TOKEN_SECRET")
        
        if not SHARED_TOKEN_SECRET:
            raise Exception("SHARED_TOKEN_SECRET is not configured")

        payload = {
            'user_id': current_user_id,
            'annotation_id': annotation_id,
            'share_type': share_type,
            'recipient_user_id': recipient_user_id
        }

        # generate a unique sharable token
        token = jwt.encode(payload, SHARED_TOKEN_SECRET, algorithm="HS256")

        # Save share entry
        shared_annotation = SharedAnnotationStorageService.save({
            'current_user_id': current_user_id,
            'annotation_id': annotation_id,
            'token': token,
            'share_type': share_type,
            'recipient_user_id': recipient_user_id,
            'role': role
        })

        if not shared_annotation:
            return JSONResponse(status_code=500, content={"error": "Failed to save shared annotation"})

        response = {
            'user_id': current_user_id,
            'annotation_id': annotation_id,
            'share_type': share_type,
            'recipient_user_id': recipient_user_id,
            'token': token,
            'role': role
        }

        return response
    except Exception as e:
        logger.error(f"Error sharing annotation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{id}")
def revoke_shared_annotation(id: str, current_user_id: str = Depends(get_current_user)):
    try:
        # Get the annotation
        annotation = AnnotationStorageService.get_by_id(id)
        if annotation is None:
            raise HTTPException(status_code=404, detail="Annotation not found")

        # Only owner can revoke
        if annotation.user_id != current_user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")

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

    except Exception as e:
        logger.error(f"Error revoking shared annotation: {e}")
        raise HTTPException(status_code=500, detail=str(e))