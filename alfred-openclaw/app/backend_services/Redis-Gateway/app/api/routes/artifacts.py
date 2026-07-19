from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.services.cloud_storage import CloudStorageService
from app.core.security import get_current_user
import json

router = APIRouter()
storage_service = CloudStorageService()

class ReportGenerationRequest(BaseModel):
    report_name: str
    report_data: dict

class ArtifactResponse(BaseModel):
    status: str
    download_url: str

@router.post("/generate", response_model=ArtifactResponse)
async def generate_and_store_artifact(
    request: ReportGenerationRequest,
    user_id: str = Depends(get_current_user)
):
    """
    Generates a report/artifact and streams it directly to the cloud bucket 
    using AWS Boto3 SDK, completely bypassing local /tmp storage to ensure 
    stateless scaling across multiple containers.
    """
    try:
        # Convert structured data to a raw JSON string for the report
        raw_report_data = json.dumps(request.report_data)
        
        # Stream the in-memory buffer directly to the cloud bucket
        download_url = storage_service.stream_report_to_cloud(
            user_id=user_id,
            report_name=request.report_name,
            report_data=raw_report_data
        )
        
        return ArtifactResponse(
            status="success",
            download_url=download_url
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to upload artifact to cloud storage.")