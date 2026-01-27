# Copyright 2026 Floriane TUERNAL SABOTINOV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pdf2image import convert_from_path
from PIL import Image
from typing import List
import os

from app.core.bundled_deps import get_poppler_path


class PDFConverter:
    """Convert PDF documents to images"""

    @staticmethod
    def pdf_to_images(pdf_path: str, dpi: int = 300) -> List[Image.Image]:
        """
        Convert PDF to list of PIL images

        Args:
            pdf_path: Path to PDF file
            dpi: Resolution for conversion (default: 300)

        Returns:
            List of PIL Image objects, one per page
        """
        try:
            images = convert_from_path(pdf_path, dpi=dpi, poppler_path=get_poppler_path())
            return images
        except Exception as e:
            raise Exception(f"Error converting PDF to images: {str(e)}")

    @staticmethod
    def save_images(images: List[Image.Image], output_dir: str, base_name: str) -> List[str]:
        """
        Save images to disk

        Args:
            images: List of PIL images
            output_dir: Directory to save images
            base_name: Base name for image files

        Returns:
            List of saved image paths
        """
        os.makedirs(output_dir, exist_ok=True)
        saved_paths = []

        for idx, image in enumerate(images):
            output_path = os.path.join(output_dir, f"{base_name}_page_{idx + 1}.png")
            image.save(output_path, "PNG")
            saved_paths.append(output_path)

        return saved_paths
