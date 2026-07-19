import boto3
import io
import os
from botocore.exceptions import ClientError
import logging

logger = logging.getLogger(__name__)

class CloudStorageService:
    def __init__(self):
        # We fetch the configuration from the native OS environment
        aws_key_id = os.environ.get("AWS_ACCESS_KEY_ID")
        aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
        if not aws_key_id or not aws_secret:
            raise RuntimeError(
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables are required"
            )

        self.bucket_name = os.environ.get("AWS_S3_BUCKET_NAME", "clax-beta-artifacts")
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=aws_key_id,
            aws_secret_access_key=aws_secret,
            region_name=os.environ.get("AWS_REGION", "ap-east-1")
        )

    def stream_report_to_cloud(self, user_id: str, report_name: str, report_data: str) -> str:
        """
        Streams generated string/JSON reports straight from memory to S3 
        without touching local container disk space (/tmp).
        """
        try:
            # Keep the artifact purely in an in-memory byte buffer
            file_buffer = io.BytesIO(report_data.encode('utf-8'))
            
            # Store under user-scoped cloud keys
            cloud_key = f"user_reports/{user_id}/{report_name}"
            
            self.s3_client.upload_fileobj(file_buffer, self.bucket_name, cloud_key)
            
            # Generate a secure short-lived presigned URL for downloading
            download_url = self.s3_client.generate_presigned_url(
                'get_object', 
                Params={'Bucket': self.bucket_name, 'Key': cloud_key}, 
                ExpiresIn=3600
            )
            return download_url
        except ClientError as e:
            logger.error(f"Failed to stream artifact to S3: {e}")
            raise

    def stream_binary_to_cloud(self, user_id: str, report_name: str, binary_data: bytes) -> str:
        """
        Streams binary artifacts (like PDFs) straight from memory to S3.
        """
        try:
            file_buffer = io.BytesIO(binary_data)
            cloud_key = f"user_artifacts/{user_id}/{report_name}"
            
            self.s3_client.upload_fileobj(file_buffer, self.bucket_name, cloud_key)
            
            download_url = self.s3_client.generate_presigned_url(
                'get_object', 
                Params={'Bucket': self.bucket_name, 'Key': cloud_key}, 
                ExpiresIn=3600
            )
            return download_url
        except ClientError as e:
            logger.error(f"Failed to stream binary artifact to S3: {e}")
            raise