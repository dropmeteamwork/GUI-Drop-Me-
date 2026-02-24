"""
Brand Recognition Module using KNN
Processes accepted items (plastic and aluminum) and classifies them by brand.
"""


# Import these FIRST before anything else
import torch
import torch.nn as nn
from torchvision import models, transforms
import boto3
from scipy.spatial.distance import cdist

import os
import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional, Tuple, Dict
from io import BytesIO

import cv2
import numpy as np
from PIL import Image
from botocore.exceptions import ClientError


class BrandRecognizer:
    """KNN-based brand recognition for accepted items"""

    def __init__(self, logger: logging.Logger, config):
        self.logger = logger
        self.config = config
        self.model_name = 'KNN'

        # S3 configuration
        self.s3_client = None
        self.bucket_name = config.AWS_BUCKET_NAME
        self.db_prefix = "brands_database/"  # S3 folder with brand folders
        self.results_prefix = "brands_results/"  # S3 output folder

        # Local cache
        self.cache_dir = Path.home() / ".local/share/dropme/gui/brand_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Recognition settings
        self.similarity_threshold = 30.0  # Euclidean distance threshold
        self.distance_metric = 'euclidean'

        # Feature extractor
        self.device = torch.device(config.DEVICE)
        self.feature_extractor = None
        self.transform = None

        # Brand database
        self.db_features = []
        self.db_labels = []
        self.db_loaded = False

        # Processing queue
        self.queue = []
        self.queue_lock = threading.Lock()

        # Initialize
        self._init_s3()
        self._init_feature_extractor()

        # Start background worker
        self.running = True
        self.worker_thread = threading.Thread(target=self._background_worker, daemon=True)
        self.worker_thread.start()

        # Load database in background
        threading.Thread(target=self._load_database, daemon=True).start()

    def _init_s3(self):
        """Initialize S3 client"""
        try:
            if self.config.AWS_ACCESS_KEY_ID and self.config.AWS_SECRET_ACCESS_KEY:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=self.config.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=self.config.AWS_SECRET_ACCESS_KEY,
                    region_name=self.config.AWS_REGION
                )
                self.logger.info("BrandRecognizer: S3 client initialized")
            else:
                self.logger.warning("BrandRecognizer: AWS credentials not set")
        except Exception as e:
            self.logger.error(f"BrandRecognizer: Failed to init S3: {e}")

    def _init_feature_extractor(self):
        """Initialize ResNet50 feature extractor"""
        try:
            self.logger.info("BrandRecognizer: Loading ResNet50 feature extractor...")
            model = models.resnet50(weights=models.ResNet50_Weights.IMAGENET1K_V1)
            # Remove final classification layer to get 2048D features
            self.feature_extractor = nn.Sequential(*list(model.children())[:-1], nn.Flatten())
            self.feature_extractor.eval()
            self.feature_extractor.to(self.device)

            # Define image transforms
            self.transform = transforms.Compose([
                transforms.Resize(256),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ])

            self.logger.info("BrandRecognizer: Feature extractor ready")
        except Exception as e:
            self.logger.error(f"BrandRecognizer: Failed to load feature extractor: {e}")

    def _load_database(self):
        """Download brand database from S3 and build feature vectors"""
        if not self.s3_client:
            self.logger.warning("BrandRecognizer: Cannot load database - S3 not available")
            return

        try:
            self.logger.info("BrandRecognizer: Downloading brand database from S3...")

            # List all objects in brands_database/
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix=self.db_prefix)

            features_list = []
            labels_list = []

            for page in pages:
                if 'Contents' not in page:
                    continue

                for obj in page['Contents']:
                    key = obj['Key']

                    # Skip if not an image
                    if not key.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                        continue

                    # Extract brand name from path: brands_database/brand_name/image.jpg
                    parts = key.split('/')
                    if len(parts) < 3:
                        continue

                    brand_name = parts[1]

                    # Download image
                    try:
                        response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
                        img_data = response['Body'].read()
                        img = Image.open(BytesIO(img_data)).convert('RGB')

                        # Extract features
                        features = self._extract_features(img)
                        features_list.append(features)
                        labels_list.append(brand_name)

                    except Exception as e:
                        self.logger.warning(f"BrandRecognizer: Failed to process {key}: {e}")
                        continue

            if features_list:
                self.db_features = np.vstack(features_list)
                self.db_labels = labels_list
                self.db_loaded = True
                self.logger.info(f"BrandRecognizer: Loaded {len(labels_list)} images from {len(set(labels_list))} brands")
            else:
                self.logger.warning("BrandRecognizer: No images found in database")

        except Exception as e:
            self.logger.error(f"BrandRecognizer: Database load failed: {e}", exc_info=True)

    def _extract_features(self, img: Image.Image) -> np.ndarray:
        """Extract 2048D feature vector from image"""
        if img.mode != 'RGB':
            img = img.convert('RGB')

        tensor = self.transform(img).unsqueeze(0).to(self.device)

        with torch.no_grad():
            features = self.feature_extractor(tensor).cpu().numpy()

        return features.flatten()

#    def queue_item(self, image_path: str, cropped_image: np.ndarray, item_type: str,
#                   phone_number: Optional[str] = None, user_id: Optional[str] = None):
#        """
#        Queue an accepted item for brand recognition
#
#        Args:
#            image_path: Path to original image
#            cropped_image: Cropped detection (BGR format from OpenCV)
#            item_type: "plastic" or "aluminum"
#        """
#        with self.queue_lock:
#            self.queue.append({
#                'image_path': image_path,
#                'cropped_image': cropped_image.copy(),
#                'item_type': item_type,
#                'queued_at': time.time(),
#                'phone_number': phone_number,
#                'user_id': user_id,  # ADD THIS
#            })


    def queue_item(self, image_path: str, cropped_image: np.ndarray, metadata: dict):
        """
        Queue an accepted item for brand recognition

        Args:
            image_path: Path to original image
            cropped_image: Cropped detection (BGR format from OpenCV)
            metadata: Complete metadata dict from item prediction
        """
        with self.queue_lock:
            self.queue.append({
                'image_path': image_path,
                'cropped_image': cropped_image.copy(),
                'metadata': metadata,  # ✅ Store entire metadata
                'queued_at': time.time()
            })

    def _background_worker(self):
        """Background thread that processes queued items"""
        while self.running:
            try:
                # Wait for database to load
                if not self.db_loaded:
                    time.sleep(5)
                    continue

                # Get next item from queue
                item = None
                with self.queue_lock:
                    if self.queue:
                        item = self.queue.pop(0)

                if item:
                    self._process_item(item)
                else:
                    time.sleep(1)

            except Exception as e:
                self.logger.error(f"BrandRecognizer: Worker error: {e}", exc_info=True)
                time.sleep(5)

#    def _process_item(self, item: dict):
#        """Process a single queued item"""
#        try:
#            phone_number = item.get('phone_number')
#            image_path = item['image_path']
#            cropped_bgr = item['cropped_image']
#            item_type = item['item_type']
#
#            # Convert BGR to RGB
#            cropped_rgb = cv2.cvtColor(cropped_bgr, cv2.COLOR_BGR2RGB)
#            pil_image = Image.fromarray(cropped_rgb)
#
#            # Extract features
#            features = self._extract_features(pil_image)
#
#            # Find nearest neighbor
#            distances = cdist(features.reshape(1, -1), self.db_features, metric=self.distance_metric)
#            min_idx = np.argmin(distances)
#            min_dist = distances[0, min_idx]
#            best_brand = self.db_labels[min_idx]
#
#            # Classify
#            if min_dist < self.similarity_threshold:
#                brand_folder = best_brand
#                confidence = 1.0 - (min_dist / 100.0)  # Rough confidence estimate
#            else:
#                brand_folder = "unknown"
#                confidence = 0.0
#
#            self.logger.info(
#                f"BrandRecognizer: {Path(image_path).name} -> {brand_folder} "
#                f"(dist={min_dist:.2f}, type={item_type})"
#            )
#
#            # Upload to S3
#            self._upload_result(image_path, cropped_bgr, brand_folder, best_brand,
#                              min_dist, confidence, item_type, phone_number)
#
#        except Exception as e:
#            self.logger.error(f"BrandRecognizer: Processing failed: {e}", exc_info=True)


    def _process_item(self, item: dict):
        """Process a single queued item"""
        try:
            # ✅ Extract metadata
            metadata = item['metadata']
            image_path = item['image_path']
            cropped_bgr = item['cropped_image']

            # Extract specific fields we need
            item_type = metadata.get('item_type', 'unknown')

            # Convert BGR to RGB
            cropped_rgb = cv2.cvtColor(cropped_bgr, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(cropped_rgb)

            # Extract features
            features = self._extract_features(pil_image)

            # Find nearest neighbor
            distances = cdist(features.reshape(1, -1), self.db_features, metric=self.distance_metric)
            min_idx = np.argmin(distances)
            min_dist = distances[0, min_idx]
            best_brand = self.db_labels[min_idx]

            # Classify
            if min_dist < self.similarity_threshold:
                brand_folder = best_brand
                confidence = 1.0 - (min_dist / 100.0)
            else:
                brand_folder = "unknown"
                confidence = 0.0

            self.logger.info(
                f"BrandRecognizer: {Path(image_path).name} -> {brand_folder} "
                f"(dist={min_dist:.2f}, type={item_type})"
            )

            # ✅ Pass full metadata to upload
            self._upload_result(
                image_path=image_path,
                cropped_image=cropped_bgr,
                brand_folder=brand_folder,
                best_match=best_brand,
                distance=min_dist,
                brand_confidence=confidence,
                metadata=metadata  # ✅ Pass entire metadata
            )

        except Exception as e:
            self.logger.error(f"BrandRecognizer: Processing failed: {e}", exc_info=True)

#    def _upload_result(self, image_path: str, cropped_image: np.ndarray,
#                      brand_folder: str, best_match: str, distance: float,
#                      confidence: float, item_type: str, phone_number: Optional[str] = None,
#                      user_id: Optional[str] = None):
#        """Upload recognized brand to S3"""
#        if not self.s3_client:
#            return
#
#        try:
#            filename = Path(image_path).name
#            timestamp = time.strftime("%Y%m%d_%H%M%S")
#
#            # Encode image as JPEG
#            _, buffer = cv2.imencode('.jpg', cropped_image, [cv2.IMWRITE_JPEG_QUALITY, 95])
#            img_bytes = buffer.tobytes()
#
#            # S3 keys
#            s3_image_key = f"{self.results_prefix}{brand_folder}/{timestamp}_{filename}"
#            s3_meta_key = f"{self.results_prefix}{brand_folder}/{timestamp}_{filename}.json"
#
#            # Metadata
#            metadata = {
#                'original_image': filename,
#                'brand_folder': brand_folder,
#                'best_match': best_match,
#                'distance': float(distance),
#                'confidence': float(confidence),
#                'threshold': self.similarity_threshold,
#                'item_type': item_type,
#                'timestamp': timestamp,
#                'machine_name': self.config.MACHINE_NAME,
#                'model_name': self.model_name,
#                'phone_number': phone_number,
#                'user_id': user_id  # ADD THIS
#
#            }
#
#            # Upload image
#            self.s3_client.put_object(
#                Bucket=self.bucket_name,
#                Key=s3_image_key,
#                Body=img_bytes,
#                ContentType='image/jpeg',
#                Metadata={'brand': brand_folder}
#            )
#
#            # Upload metadata
#            self.s3_client.put_object(
#                Bucket=self.bucket_name,
#                Key=s3_meta_key,
#                Body=json.dumps(metadata, indent=2),
#                ContentType='application/json'
#            )
#
#            self.logger.info(f"BrandRecognizer: Uploaded to s3://{self.bucket_name}/{s3_image_key}")
#
#        except Exception as e:
#            self.logger.error(f"BrandRecognizer: Upload failed: {e}", exc_info=True)


    def _upload_result(self, image_path: str, cropped_image: np.ndarray,
                      brand_folder: str, best_match: str, distance: float,
                      brand_confidence: float, metadata: dict):
        """Upload recognized brand to S3"""
        if not self.s3_client:
            return

        try:
            filename = Path(image_path).name
            timestamp = time.strftime("%Y%m%d_%H%M%S")

            # Encode image as JPEG
            _, buffer = cv2.imencode('.jpg', cropped_image, [cv2.IMWRITE_JPEG_QUALITY, 95])
            img_bytes = buffer.tobytes()

            # S3 keys
            s3_image_key = f"{self.results_prefix}{brand_folder}/{timestamp}_{filename}"
            s3_meta_key = f"{self.results_prefix}{brand_folder}/{timestamp}_{filename}.json"

            # ✅ Build brand metadata by extending item prediction metadata
            brand_metadata = metadata.copy()  # Start with ALL item prediction fields

            # Add brand-specific fields
            brand_metadata.update({
                'brand_folder': brand_folder,
                'brand_best_match': best_match,
                'brand_distance': float(distance),
                'brand_confidence': float(brand_confidence),
                'brand_threshold': self.similarity_threshold,
                'brand_model_name': self.model_name,
                'brand_image_s3_key': s3_image_key,
                'brand_timestamp': timestamp
            })

            # Upload image
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_image_key,
                Body=img_bytes,
                ContentType='image/jpeg',
                Metadata={'brand': brand_folder}
            )

            # Upload metadata
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_meta_key,
                Body=json.dumps(brand_metadata, indent=2),
                ContentType='application/json'
            )

            self.logger.info(f"BrandRecognizer: Uploaded to s3://{self.bucket_name}/{s3_image_key}")

        except Exception as e:
            self.logger.error(f"BrandRecognizer: Upload failed: {e}", exc_info=True)


    def update_user_id_for_capture(self, image_path: str, user_id: int):
        """Update user_id in queued brand recognition items"""
        try:
            with self.queue_lock:
                updated_count = 0
                for item in self.queue:
                    if item.get('image_path') == image_path:
                        if 'metadata' in item:
                            item['metadata']['user_id'] = user_id
                            updated_count += 1
                            self.logger.info(f"BrandRecognizer: Updated user_id={user_id} for {Path(image_path).name}")

                if updated_count == 0:
                    self.logger.warning(f"BrandRecognizer: No queued items found for {image_path}")

        except Exception as e:
            self.logger.error(f"BrandRecognizer: Failed to update user_id: {e}")

    def get_stats(self) -> Dict:
        """Get current statistics"""
        with self.queue_lock:
            return {
                'queue_size': len(self.queue),
                'database_loaded': self.db_loaded,
                'num_brands': len(set(self.db_labels)) if self.db_loaded else 0,
                'num_reference_images': len(self.db_labels) if self.db_loaded else 0
            }

    def shutdown(self):
        """Stop background worker"""
        self.running = False
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5)
