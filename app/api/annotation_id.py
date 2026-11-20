from typing import Annotated

from bson import ObjectId
from fastapi import Depends, HTTPException
from starlette.convertors import StringConvertor, register_url_convertor


class AnnotationIDConvertor(StringConvertor):
    regex = r"[0-9a-fA-F]{24}"


register_url_convertor("annotation_id", AnnotationIDConvertor())


def validate_annotation_id(id: str) -> str:
    if not isinstance(id, str) or not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid annotation ID")
    return str(ObjectId(id))


AnnotationID = Annotated[str, Depends(validate_annotation_id)]
