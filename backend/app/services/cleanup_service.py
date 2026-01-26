"""
Cleanup Service - Manage temporary files and expired analysis jobs.

Handles:
- Cleanup of expired analysis jobs (> 1 hour old)
- Deletion of temporary files for completed/expired jobs
- Manual cleanup endpoint support
"""

import os
import glob
import shutil
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session
import structlog

from app.core.config import settings
from app.models.analysis_job import AnalysisJob

logger = structlog.get_logger(__name__)


class CleanupService:
    """
    Service for cleaning up expired jobs and temporary files.

    Temp file structure:
    {DATA_DIR}/temp/
    ├── {job_id}_original.{ext}      # Uploaded file
    ├── {job_id}_preprocessed.png    # Preprocessed image
    ├── {job_id}_page_{n}.png        # Multi-page PDF pages
    └── ...
    """

    def __init__(self):
        self.temp_dir = settings.TEMP_DIR

    def ensure_temp_dir(self):
        """Create temp directory if it doesn't exist"""
        os.makedirs(self.temp_dir, exist_ok=True)
        logger.debug("Temp directory ensured", path=self.temp_dir)

    def get_job_file_path(self, job_id: str, file_type: str, extension: str = None, page: int = None) -> str:
        """
        Get path for a job file.

        Args:
            job_id: Job UUID
            file_type: Type of file ('original', 'preprocessed', 'page')
            extension: File extension (for 'original' type)
            page: Page number (for 'page' type)

        Returns:
            Full path to the file
        """
        if file_type == 'original':
            ext = extension or 'tmp'
            return os.path.join(self.temp_dir, f"{job_id}_original.{ext}")
        elif file_type == 'preprocessed':
            return os.path.join(self.temp_dir, f"{job_id}_preprocessed.png")
        elif file_type == 'page':
            page_num = page or 0
            return os.path.join(self.temp_dir, f"{job_id}_page_{page_num}.png")
        else:
            raise ValueError(f"Unknown file type: {file_type}")

    def get_all_job_files(self, job_id: str) -> List[str]:
        """
        Get all file paths associated with a job.

        Returns:
            List of file paths that exist for the job
        """
        pattern = os.path.join(self.temp_dir, f"{job_id}_*")
        return glob.glob(pattern)

    def cleanup_job_files(self, job_id: str) -> Dict[str, Any]:
        """
        Delete all temporary files for a specific job.

        Args:
            job_id: Job UUID

        Returns:
            {
                'success': bool,
                'files_deleted': int,
                'errors': list
            }
        """
        files = self.get_all_job_files(job_id)

        if not files:
            logger.debug("No files found for job", job_id=job_id)
            return {
                'success': True,
                'files_deleted': 0,
                'errors': []
            }

        deleted = 0
        errors = []

        for file_path in files:
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    deleted += 1
                    logger.debug("Deleted file", path=file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    deleted += 1
            except Exception as e:
                errors.append(f"{file_path}: {str(e)}")
                logger.error("Failed to delete file", path=file_path, error=str(e))

        logger.info("Job files cleaned up", job_id=job_id, deleted=deleted)

        return {
            'success': len(errors) == 0,
            'files_deleted': deleted,
            'errors': errors
        }

    def cleanup_expired_jobs(self, db: Session) -> Dict[str, Any]:
        """
        Find and clean up all expired jobs.

        Jobs are expired if:
        - expires_at < now AND status is 'analyzed' (never processed)

        Args:
            db: Database session

        Returns:
            {
                'jobs_expired': int,
                'jobs_cleaned': int,
                'files_deleted': int,
                'errors': list
            }
        """
        now = datetime.utcnow()

        # Find expired jobs that haven't been cleaned up
        expired_jobs = db.query(AnalysisJob).filter(
            AnalysisJob.expires_at < now,
            AnalysisJob.status.in_(['analyzed', 'processing'])
        ).all()

        if not expired_jobs:
            logger.info("No expired jobs to clean up")
            return {
                'jobs_expired': 0,
                'jobs_cleaned': 0,
                'files_deleted': 0,
                'errors': []
            }

        jobs_cleaned = 0
        total_files_deleted = 0
        all_errors = []

        for job in expired_jobs:
            # Clean up files
            cleanup_result = self.cleanup_job_files(job.id)
            total_files_deleted += cleanup_result['files_deleted']
            all_errors.extend(cleanup_result['errors'])

            # Mark job as expired
            job.mark_expired()
            jobs_cleaned += 1

        db.commit()

        logger.info(
            "Expired jobs cleaned up",
            jobs_cleaned=jobs_cleaned,
            files_deleted=total_files_deleted,
            errors_count=len(all_errors)
        )

        return {
            'jobs_expired': len(expired_jobs),
            'jobs_cleaned': jobs_cleaned,
            'files_deleted': total_files_deleted,
            'errors': all_errors
        }
        
    def force_cleanup(self, db: Session) -> Dict[str, Any]:
        """
        Force cleanup of all jobs and their files.

        Args:
            db: Database session
        """
        all_jobs = db.query(AnalysisJob).all()

        jobs_cleaned = 0
        total_files_deleted = 0
        all_errors = []

        for job in all_jobs:
            # Clean up files
            cleanup_result = self.cleanup_job_files(job.id)
            total_files_deleted += cleanup_result['files_deleted']
            all_errors.extend(cleanup_result['errors'])

            # Delete job from database
            db.delete(job)
            jobs_cleaned += 1

        db.commit()

        logger.info(
            "Force cleanup completed",
            jobs_cleaned=jobs_cleaned,
            files_deleted=total_files_deleted,
            errors_count=len(all_errors)
        )

        return {
            'expired_jobs': {
                'jobs_expired': jobs_cleaned,
                'jobs_cleaned': jobs_cleaned,
                'files_deleted': total_files_deleted
            },
            'total_files_deleted': total_files_deleted,
            'errors': all_errors
        }
        

    def cleanup_completed_job(self, job_id: str, db: Session) -> Dict[str, Any]:
        """
        Returns:
            Cleanup result dict
        """
        return self.cleanup_job_files(job_id)

    def cleanup_orphaned_files(self, db: Session) -> Dict[str, Any]:
        """
        Find and delete temp files that don't have corresponding jobs.

        This handles cases where jobs were deleted but files remained.

        Args:
            db: Database session

        Returns:
            {
                'files_deleted': int,
                'errors': list
            }
        """
        if not os.path.exists(self.temp_dir):
            return {'files_deleted': 0, 'errors': []}

        # Get all job IDs from temp files
        all_files = glob.glob(os.path.join(self.temp_dir, "*_*"))
        job_ids_from_files = set()

        for file_path in all_files:
            filename = os.path.basename(file_path)
            # Extract job_id (UUID before first underscore after job_id)
            parts = filename.split('_')
            if len(parts) >= 5:  # UUID has 5 parts when split by hyphen
                # Reconstruct UUID from first 5 parts
                job_id = '-'.join(parts[0].split('-')[:5]) if '-' in parts[0] else None
                if job_id and len(job_id) == 36:
                    job_ids_from_files.add(job_id)

        if not job_ids_from_files:
            return {'files_deleted': 0, 'errors': []}

        # Get existing job IDs from database
        existing_jobs = db.query(AnalysisJob.id).filter(
            AnalysisJob.id.in_(list(job_ids_from_files))
        ).all()
        existing_job_ids = {job.id for job in existing_jobs}

        # Find orphaned job IDs
        orphaned_job_ids = job_ids_from_files - existing_job_ids

        if not orphaned_job_ids:
            return {'files_deleted': 0, 'errors': []}

        # Clean up orphaned files
        total_deleted = 0
        all_errors = []

        for job_id in orphaned_job_ids:
            result = self.cleanup_job_files(job_id)
            total_deleted += result['files_deleted']
            all_errors.extend(result['errors'])

        logger.info(
            "Orphaned files cleaned up",
            orphaned_jobs=len(orphaned_job_ids),
            files_deleted=total_deleted
        )

        return {
            'files_deleted': total_deleted,
            'errors': all_errors
        }

    def get_temp_dir_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the temp directory.

        Returns:
            {
                'exists': bool,
                'file_count': int,
                'total_size_mb': float,
                'path': str
            }
        """
        if not os.path.exists(self.temp_dir):
            return {
                'exists': False,
                'file_count': 0,
                'total_size_mb': 0.0,
                'path': self.temp_dir
            }

        files = glob.glob(os.path.join(self.temp_dir, "*"))
        total_size = sum(os.path.getsize(f) for f in files if os.path.isfile(f))

        return {
            'exists': True,
            'file_count': len(files),
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'path': self.temp_dir
        }

    def full_cleanup(self, db: Session) -> Dict[str, Any]:
        """
        Perform a full cleanup: expired jobs and orphaned files.

        Args:
            db: Database session

        Returns:
            Combined cleanup results
        """
        # Clean expired jobs first
        expired_result = self.cleanup_expired_jobs(db)

        # Then clean orphaned files
        orphaned_result = self.cleanup_orphaned_files(db)

        return {
            'expired_jobs': {
                'jobs_expired': expired_result['jobs_expired'],
                'jobs_cleaned': expired_result['jobs_cleaned'],
                'files_deleted': expired_result['files_deleted']
            },
            'orphaned_files': {
                'files_deleted': orphaned_result['files_deleted']
            },
            'total_files_deleted': expired_result['files_deleted'] + orphaned_result['files_deleted'],
            'errors': expired_result['errors'] + orphaned_result['errors']
        }
