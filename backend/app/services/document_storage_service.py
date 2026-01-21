"""
Document Storage Service - Manage permanent storage of original invoice documents.

Handles:
- Storing original documents permanently after processing
- Retrieving document paths for serving
- Deleting documents when invoices are deleted
"""

import os
import shutil
from typing import Optional
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


class DocumentStorageService:
    """
    Service for permanent document storage.

    Document storage structure:
    documents/
    └── {invoice_id}_{original_filename}
    """

    def __init__(self):
        self.documents_dir = settings.DOCUMENTS_DIR

    def ensure_documents_dir(self):
        """Create documents directory if it doesn't exist"""
        os.makedirs(self.documents_dir, exist_ok=True)
        logger.debug("Documents directory ensured", path=self.documents_dir)

    def get_stored_filename(self, invoice_id: int, original_filename: str) -> str:
        """
        Generate the stored filename for a document.

        Args:
            invoice_id: The invoice ID
            original_filename: Original filename from upload

        Returns:
            Filename in format: {invoice_id}_{original_filename}
        """
        # Sanitize filename to prevent path traversal
        safe_filename = os.path.basename(original_filename)
        return f"{invoice_id}_{safe_filename}"

    def get_document_path(self, stored_filename: str) -> str:
        """
        Get the full path to a stored document.

        Args:
            stored_filename: The stored filename

        Returns:
            Full path to the document
        """
        return os.path.join(self.documents_dir, stored_filename)

    def store_document(
        self,
        source_path: str,
        invoice_id: int,
        original_filename: str
    ) -> Optional[str]:
        """
        Copy a document from temp storage to permanent storage.

        Args:
            source_path: Path to the source file (in temp directory)
            invoice_id: The invoice ID
            original_filename: Original filename from upload

        Returns:
            Stored filename if successful, None if failed
        """
        try:
            # Check if source file exists
            if not os.path.isfile(source_path):
                logger.warning(
                    "Source file not found for document storage",
                    source_path=source_path,
                    invoice_id=invoice_id
                )
                return None

            self.ensure_documents_dir()

            stored_filename = self.get_stored_filename(invoice_id, original_filename)
            dest_path = self.get_document_path(stored_filename)

            logger.debug(
                "Copying document to permanent storage",
                source_path=source_path,
                dest_path=dest_path
            )

            # Copy file to permanent storage
            shutil.copy2(source_path, dest_path)

            # Verify copy was successful
            if not os.path.isfile(dest_path):
                logger.error("Document copy verification failed", dest_path=dest_path)
                return None

            logger.info(
                "Document stored permanently",
                invoice_id=invoice_id,
                original_filename=original_filename,
                stored_filename=stored_filename,
                dest_path=dest_path
            )

            return stored_filename

        except Exception as e:
            logger.error(
                "Failed to store document",
                invoice_id=invoice_id,
                source_path=source_path,
                error=str(e)
            )
            return None

    def delete_document(self, stored_filename: str) -> bool:
        """
        Delete a document from permanent storage.

        Args:
            stored_filename: The stored filename

        Returns:
            True if deleted successfully or file didn't exist, False on error
        """
        try:
            file_path = self.get_document_path(stored_filename)

            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info("Document deleted", filename=stored_filename)

            return True

        except Exception as e:
            logger.error(
                "Failed to delete document",
                filename=stored_filename,
                error=str(e)
            )
            return False

    def document_exists(self, stored_filename: str) -> bool:
        """
        Check if a document exists in storage.

        Args:
            stored_filename: The stored filename

        Returns:
            True if document exists
        """
        file_path = self.get_document_path(stored_filename)
        return os.path.isfile(file_path)

    def get_media_type(self, filename: str) -> str:
        """
        Get the media type for a file based on extension.

        Args:
            filename: Filename with extension

        Returns:
            MIME type string
        """
        ext = os.path.splitext(filename)[1].lower()
        media_types = {
            '.pdf': 'application/pdf',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.tiff': 'image/tiff',
            '.tif': 'image/tiff',
            '.webp': 'image/webp',
            '.bmp': 'image/bmp',
        }
        return media_types.get(ext, 'application/octet-stream')


# Global instance
document_storage_service = DocumentStorageService()
