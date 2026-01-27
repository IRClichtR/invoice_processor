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

import cv2
import numpy as np
from PIL import Image
from typing import Union


class ImagePreprocessor:
    """Image preprocessing for OCR optimization"""

    @staticmethod
    def pil_to_cv2(image: Image.Image) -> np.ndarray:
        """Convert PIL Image to OpenCV format"""
        return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

    @staticmethod
    def cv2_to_pil(image: np.ndarray) -> Image.Image:
        """Convert OpenCV image to PIL format"""
        return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

    @staticmethod
    def deskew(image: np.ndarray, angle_threshold: float = 0.5) -> np.ndarray:
        """
        Deskew image by detecting rotation angle
        Only applies rotation if angle is significant

        Args:
            image: OpenCV image (BGR format)
            angle_threshold: Minimum angle to trigger rotation (degrees)

        Returns:
            Deskewed image
        """
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Apply threshold to get binary image
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

        # Find coordinates of all non-zero points
        coords = np.column_stack(np.where(thresh > 0))

        if len(coords) < 100:
            # Not enough points to determine skew
            return image

        # Find minimum area rectangle
        angle = cv2.minAreaRect(coords)[-1]

        # Adjust angle
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        # Only rotate if angle is significant
        if abs(angle) < angle_threshold:
            return image

        # Rotate image
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(image, M, (w, h),
                                 flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_REPLICATE)

        return rotated

    @staticmethod
    def apply_clahe(image: np.ndarray, clip_limit: float = 1.5, tile_size: int = 8) -> np.ndarray:
        """
        Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
        Uses gentler settings to avoid over-enhancement

        Args:
            image: OpenCV image (BGR format)
            clip_limit: Threshold for contrast limiting (reduced from 2.0 to 1.5)
            tile_size: Size of grid for histogram equalization

        Returns:
            Contrast enhanced image
        """
        # Convert to LAB color space
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        # Apply CLAHE to L channel with gentler settings
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_size, tile_size))
        cl = clahe.apply(l)

        # Merge channels
        limg = cv2.merge((cl, a, b))

        # Convert back to BGR
        enhanced = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

        return enhanced

    @staticmethod
    def denoise(image: np.ndarray, strength: int = 5) -> np.ndarray:
        """
        Apply denoising to image
        Uses gentler strength to preserve details

        Args:
            image: OpenCV image (BGR format)
            strength: Denoising strength (reduced from 10 to 5)

        Returns:
            Denoised image
        """
        return cv2.fastNlMeansDenoisingColored(image, None, strength, strength, 7, 21)

    @staticmethod
    def binarize(image: np.ndarray, method: str = "otsu") -> np.ndarray:
        """
        Apply binarization to image

        Args:
            image: OpenCV image (BGR format)
            method: Binarization method ("otsu" or "adaptive")

        Returns:
            Binarized image
        """
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        if method == "otsu":
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        elif method == "adaptive":
            binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                          cv2.THRESH_BINARY, 11, 2)
        else:
            raise ValueError(f"Unknown binarization method: {method}")

        # Convert back to BGR for consistency
        return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)

    @classmethod
    def preprocess(cls, image: Union[Image.Image, np.ndarray],
                   apply_deskew: bool = True,
                   apply_clahe_filter: bool = True,
                   apply_denoise_filter: bool = True,
                   apply_binarize: bool = False) -> Image.Image:
        """
        Apply full preprocessing pipeline

        Args:
            image: PIL Image or OpenCV image
            apply_deskew: Apply deskewing
            apply_clahe_filter: Apply CLAHE contrast enhancement
            apply_denoise_filter: Apply denoising
            apply_binarize: Apply binarization

        Returns:
            Preprocessed PIL Image
        """
        # Convert to OpenCV format if needed
        if isinstance(image, Image.Image):
            cv2_image = cls.pil_to_cv2(image)
        else:
            cv2_image = image

        # Apply preprocessing steps
        if apply_deskew:
            cv2_image = cls.deskew(cv2_image)

        if apply_clahe_filter:
            cv2_image = cls.apply_clahe(cv2_image)

        if apply_denoise_filter:
            cv2_image = cls.denoise(cv2_image)

        if apply_binarize:
            cv2_image = cls.binarize(cv2_image)

        # Convert back to PIL
        return cls.cv2_to_pil(cv2_image)
