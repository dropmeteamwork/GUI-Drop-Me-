import json
import boto3
import os
from datetime import datetime
from botocore.exceptions import ClientError, EndpointConnectionError
from pathlib import Path
import tempfile
import threading
import time
from typing import Optional, Tuple

AWS_DEBUG_LOG = Path(tempfile.gettempdir()) / "aws_debug.log"

def _load_test_config():
    """
    Search for a local JSON config named 'dropme_config.json' starting
    from this file's directory and moving up the parent directories.
    Returns a dict or {} on failure.
    """
    from pathlib import Path
    import json
    try:
        for parent in Path(__file__).resolve().parents:
            cfg_path = parent / 'dropme_config.json'
            if cfg_path.exists():
                with open(cfg_path, 'r') as f:
                    return json.load(f)
    except Exception:
        pass
    return {}

class AWSUploader:
    """Upload images and predictions to AWS S3"""

    #def __init__(self):
        # self.bucket_name = os.getenv('AWS_BUCKET_NAME', 'ai-data-001')
        # aws_key = os.getenv('AWS_ACCESS_KEY_ID', '')
        # aws_secret = os.getenv('AWS_SECRET_ACCESS_KEY', '')
        # aws_region = os.getenv('AWS_REGION', 'eu-central-1')
        # self.machine_name = os.getenv('MACHINE_NAME', 'maadi_club')

    def __init__(self):
        # Load dropme_config.json for testing (if present)
        cfg = _load_test_config()
        if cfg:
            # Use values from the config file for testing
            self.bucket_name = cfg.get('AWS_BUCKET_NAME_TEST') or cfg.get('AWS_BUCKET_NAME', 'ai-data-001')
            aws_key     = cfg.get('AWS_ACCESS_KEY_ID', '')
            aws_secret  = cfg.get('AWS_SECRET_ACCESS_KEY', '')
            aws_region  = cfg.get('AWS_REGION', 'eu-central-1')
            self.machine_name = cfg.get('MACHINE_NAME', 'maadi_club')
        else:
            # Default production behaviour
            self.bucket_name = os.getenv('AWS_BUCKET_NAME', 'ai-data-001')
            aws_key     = os.getenv('AWS_ACCESS_KEY_ID', '')
            aws_secret  = os.getenv('AWS_SECRET_ACCESS_KEY', '')
            aws_region  = os.getenv('AWS_REGION', 'eu-central-1')
            self.machine_name = os.getenv('MACHINE_NAME', 'maadi_club')

        #for offline sync
        self.captures_dir = Path.home() / ".local/share/dropme/gui/captures"
        self.metadata_dir = Path.home() / ".local/share/dropme/gui/metadata"
        self.queue_dir = Path.home() / ".local/share/dropme/gui/upload_queue"

        # Create directories
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.queue_dir.mkdir(parents=True, exist_ok=True)


        if not aws_key or not aws_secret:
            print("[AWSUploader] WARNING: AWS credentials not set")
            self.s3_client = None
            return

        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=aws_key,
                aws_secret_access_key=aws_secret,
                region_name=aws_region
            )
            print(f"[AWSUploader] Initialized for bucket: {self.bucket_name}")
        except Exception as e:
            print(f"[AWSUploader] Failed to initialize: {e}")
            self.s3_client = None

        # Start background sync thread
        self.sync_thread = threading.Thread(target=self._background_sync, daemon=True)
        self.sync_thread.start()

        # Sync existing captures on startup
        #threading.Thread(target=self._sync_existing_captures, daemon=True).start()


    def _is_online(self) -> bool:
        """Check if S3 is accessible"""
        with open(AWS_DEBUG_LOG, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now()}: Checking online status\n")
            f.write(f"{datetime.now()}: s3_client exists: {self.s3_client is not None}\n")
            f.write(f"{datetime.now()}: bucket_name: {self.bucket_name}\n")

        if self.s3_client is None:
            with open(AWS_DEBUG_LOG, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now()}: s3_client is None - returning False\n")
            return False

        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            with open(AWS_DEBUG_LOG, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now()}: head_bucket SUCCESS - returning True\n")
            return True
        except Exception as e:
            with open(AWS_DEBUG_LOG, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now()}: Exception: {type(e).__name__} - {str(e)}\n")
            return False

    def _save_to_queue(self, queue_item: dict) -> bool:
        """Save upload job to local queue"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            # ✅ Include capture_id in filename for easier lookup
            capture_id = queue_item.get('prediction_data', {}).get('capture_id', 'unknown')
            queue_file = self.queue_dir / f"queue_{timestamp}_{capture_id}.json"
            #queue_file = self.queue_dir / f"queue_{timestamp}.json"
            with open(queue_file, 'w') as f:
                json.dump(queue_item, f, indent=2)
            print(f"[AWSUploader] Saved to queue: {queue_file.name}")
            return True
        except Exception as e:
            print(f"[AWSUploader] Failed to save to queue: {e}")
            return False

    def _save_metadata_locally(self, metadata: dict, capture_id: str) -> bool:
        """Save metadata to local metadata directory"""
        try:
            metadata_file = self.metadata_dir / f"{capture_id}.json"
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            print(f"[AWSUploader] Saved metadata locally: {metadata_file.name}")
            return True
        except Exception as e:
            print(f"[AWSUploader] Failed to save metadata locally: {e}")
            return False


    ######################## with time tracking
#    def upload_prediction(self, image_path: str, item: str, confidence: float,
#                          prediction_image_bytes: bytes,
#                          machine_name: str,
#                          phone_number: Optional[str] = None,
#                          user_id: Optional[str] = None,  # ADD THIS NEW PARAMETER
#                          status: str = "unknown",
#                          bbox: Optional[Tuple[int, int, int, int]] = None,
#                          timings: Optional[dict] = None,
#                          yolo_model: Optional[str] = None,
#                          classifier_model: Optional[str] = None,
#                          operation_mode: Optional[str] = None) -> dict:
#        """Upload prediction to S3 or queue if offline - NON-BLOCKING
#
#        timings: optional dict with timing measurements (ms) from ML pipeline
#        """
#        if not os.path.exists(image_path):
#            print(f"[AWSUploader] Image not found: {image_path}")
#            return {'success': False, 'error': 'Image file not found'}
#
#        # Prepare metadata
#        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#        image_file = Path(image_path)
#        safe_machine = machine_name.replace("'", "").replace(" ", "_")
#        capture_id = image_file.stem
#
#        s3_image_key = f"captures/{safe_machine}/{timestamp}/{image_file.name}"
#        s3_json_key = f"predictions/{safe_machine}/{timestamp}/prediction.json"
#
#        prediction_data = {
#            'capture_id': capture_id,
#            'machine_name': machine_name,
#            'item_type': item,
#            'confidence': round(float(confidence), 3),
#            'decision': status,
#            'rejection_reason': 'NONE',
#            'timestamp': str(int(time.time())),
#            'classifier_confidence': 0.0,
#            'operation_mode': operation_mode or 'unknown',
#            'yolo_model': yolo_model,
#            'classifier_model': classifier_model,
#            'image_s3_key': s3_image_key,
#            'bbox': {'x1': bbox[0], 'y1': bbox[1], 'x2': bbox[2], 'y2': bbox[3]} if bbox else None,
#            'timings': timings if timings is not None else {},
#            'phone_number': phone_number,
#            'user_id': user_id  # ADD THIS - will be null if not provided
#        }
#
#
#        # Always save metadata locally (fast)
#        self._save_metadata_locally(prediction_data, capture_id)
#
#        # Queue immediately - don't check if online (that's slow!)
#        queue_item = {
#            'image_path': str(image_path),
#            'image_s3_key': s3_image_key,
#            'json_s3_key': s3_json_key,
#            'prediction_data': prediction_data,
#            'bbox': bbox,
#            'queued_at': datetime.now().isoformat()
#        }
#
#        self._save_to_queue(queue_item)
#
#        return {
#            'success': True,
#            'queued': True,
#            'message': 'Queued for background upload'
#        }


    def update_metadata_with_user_id(self, capture_id: str, user_id: int):
        """Update local metadata and queue with user_id after prediction is done"""
        try:
            # 1. Update local metadata file
            metadata_file = self.metadata_dir / f"{capture_id}.json"
            if metadata_file.exists():
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)

                metadata['user_id'] = user_id

                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)

                print(f"[AWSUploader] Updated local metadata for {capture_id} with user_id={user_id}")
            else:
                print(f"[AWSUploader] WARNING: Metadata file not found for {capture_id}")
                return

            # 2. Update queue file if it exists
            queue_files = list(self.queue_dir.glob(f"queue_*{capture_id}*.json"))
            for queue_file in queue_files:
                try:
                    with open(queue_file, 'r') as f:
                        queue_item = json.load(f)

                    # Update the prediction_data in the queue
                    if 'prediction_data' in queue_item:
                        queue_item['prediction_data']['user_id'] = user_id

                        with open(queue_file, 'w') as f:
                            json.dump(queue_item, f, indent=2)

                        print(f"[AWSUploader] Updated queue file {queue_file.name} with user_id={user_id}")
                except Exception as e:
                    print(f"[AWSUploader] Error updating queue file {queue_file.name}: {e}")

        except Exception as e:
            print(f"[AWSUploader] Error updating metadata with user_id: {e}")

    def upload_prediction_metadata_only(self, metadata: dict) -> dict:
        """
        DEV mode helper: queue ONLY the prediction metadata JSON for upload.
        Uses the same queue + background sync as image uploads.
        """
        # Build keys same style as upload_prediction
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        machine_name = metadata.get('machine_name', self.machine_name)
        safe_machine = machine_name.replace("'", "").replace(" ", "_")
        capture_id = metadata.get('capture_id') or datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        # Put JSON under predictions/... just like normal
        s3_json_key = f"predictions/{safe_machine}/{timestamp}/prediction.json"

        prediction_data = metadata.copy()

        # Still save locally (optional but consistent with your design)
        self._save_metadata_locally(prediction_data, capture_id)

        queue_item = {
            "mode": "metadata_only",
            "json_s3_key": s3_json_key,
            "prediction_data": prediction_data,
            "queued_at": datetime.now().isoformat(),
        }

        self._save_to_queue(queue_item)

        return {"success": True, "queued": True, "message": "Queued metadata-only upload"}

    def upload_prediction(self,
                          image_path: str,
                          prediction_image_bytes: bytes,
                          metadata: dict) -> dict:  # ✅ Accept metadata dict
        """Upload prediction to S3 or queue if offline - NON-BLOCKING"""

        if not os.path.exists(image_path):
            print(f"[AWSUploader] Image not found: {image_path}")
            return {'success': False, 'error': 'Image file not found'}

        # Extract what we need from metadata
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_file = Path(image_path)
        machine_name = metadata.get('machine_name', self.machine_name)
        safe_machine = machine_name.replace("'", "").replace(" ", "_")
        capture_id = metadata.get('capture_id', image_file.stem)

        s3_image_key = f"captures/{safe_machine}/{timestamp}/{image_file.name}"
        s3_json_key = f"predictions/{safe_machine}/{timestamp}/prediction.json"

        # ✅ Use the metadata dict directly (add S3 keys)
        prediction_data = metadata.copy()
        prediction_data['image_s3_key'] = s3_image_key

        # Always save metadata locally (fast)
        self._save_metadata_locally(prediction_data, capture_id)

        # Queue immediately
        bbox = metadata.get('bbox')
        bbox_tuple = None
        if bbox and isinstance(bbox, dict):
            bbox_tuple = (bbox['x1'], bbox['y1'], bbox['x2'], bbox['y2'])

        queue_item = {
            'image_path': str(image_path),
            'image_s3_key': s3_image_key,
            'json_s3_key': s3_json_key,
            'prediction_data': prediction_data,
            'bbox': bbox_tuple,
            'queued_at': datetime.now().isoformat()
        }

        self._save_to_queue(queue_item)

        return {
            'success': True,
            'queued': True,
            'message': 'Queued for background upload'
        }

    def _upload_to_s3(self, image_path: str, s3_image_key: str, s3_json_key: str,
                     prediction_data: dict, bbox: Optional[Tuple[int, int, int, int]]) -> dict:
        """Perform the actual S3 upload"""
        extra_args = {'ContentType': 'image/jpeg'}
        if bbox is not None:
            x1, y1, x2, y2 = map(int, bbox)
            extra_args['Metadata'] = {'bbox': f"{x1},{y1},{x2},{y2}"}

        # Upload image
        self.s3_client.upload_file(
            image_path,
            self.bucket_name,
            s3_image_key,
            ExtraArgs=extra_args
        )

        # Upload JSON
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=s3_json_key,
            Body=json.dumps(prediction_data, indent=2),
            ContentType='application/json'
        )

        print(f"[AWSUploader] Successfully uploaded: {s3_image_key}")

        return {
            'success': True,
            'queued': False,
            'image_url': f"https://{self.bucket_name}.s3.amazonaws.com/{s3_image_key}",
            'json_url': f"https://{self.bucket_name}.s3.amazonaws.com/{s3_json_key}"
    }

    def _process_queue_item(self, queue_file: Path) -> bool:
        """Process a single queued upload"""
        try:
            with open(queue_file, 'r') as f:
                queue_item = json.load(f)
                mode = queue_item.get("mode", "image_and_json")
            if mode == "metadata_only":
                try:
                    if self.s3_client is None:
                        return False

                    self.s3_client.put_object(
                        Bucket=self.bucket_name,
                        Key=queue_item["json_s3_key"],
                        Body=json.dumps(queue_item["prediction_data"], indent=2),
                        ContentType='application/json'
                    )

                    queue_file.unlink()
                    print(f"[AWSUploader] Uploaded metadata-only: {queue_item['json_s3_key']}")
                    return True

                except Exception as e:
                    print(f"[AWSUploader] Error uploading metadata-only {queue_file.name}: {e}")
                    return False
    
            image_path = queue_item['image_path']
            if not os.path.exists(image_path):
                print(f"[AWSUploader] Queued image not found: {image_path}, removing from queue")
                queue_file.unlink()
                return True

            result = self._upload_to_s3(
                image_path=image_path,
                s3_image_key=queue_item['image_s3_key'],
                s3_json_key=queue_item['json_s3_key'],
                prediction_data=queue_item['prediction_data'],
                bbox=tuple(queue_item['bbox']) if queue_item.get('bbox') else None
            )

            if result['success']:
                queue_file.unlink()
                print(f"[AWSUploader] Successfully processed queued item: {queue_file.name}")
                return True
            return False

        except Exception as e:
            print(f"[AWSUploader] Error processing queue item {queue_file.name}: {e}")
            return False

    def _sync_existing_captures(self):
        """Scan captures directory for files without metadata and create queue entries"""
        print("[AWSUploader] Scanning for existing captures without metadata...")
        try:
            if not self.captures_dir.exists():
                return

            for image_file in self.captures_dir.glob("*.jpg"):
                capture_id = image_file.stem
                metadata_file = self.metadata_dir / f"{capture_id}.json"

                # If metadata doesn't exist, this capture was never uploaded
                if not metadata_file.exists():
                    print(f"[AWSUploader] Found unprocessed capture: {image_file.name}")

                    # Create basic metadata
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_machine = self.machine_name.replace("'", "").replace(" ", "_")

                    s3_image_key = f"captures/{safe_machine}/{timestamp}/{image_file.name}"
                    s3_json_key = f"predictions/{safe_machine}/{timestamp}/prediction.json"

                    prediction_data = {
                        'capture_id': capture_id,
                        'machine_name': self.machine_name,
                        'item_type': 'unknown',
                        'confidence': 0.0,
                        'decision': 'BACKFILLED',
                        'rejection_reason': 'NONE',
                        'timestamp': str(int(time.time())),
                        'classifier_confidence': 0.0,
                        'operation_mode': 'backfill',
                        'image_s3_key': s3_image_key,
                        'bbox': None,
                        'note': 'Backfilled from offline captures'
                    }

                    # Save metadata locally
                    self._save_metadata_locally(prediction_data, capture_id)

                    # Queue for upload
                    queue_item = {
                        'image_path': str(image_file),
                        'image_s3_key': s3_image_key,
                        'json_s3_key': s3_json_key,
                        'prediction_data': prediction_data,
                        'bbox': None,
                        'queued_at': datetime.now().isoformat()
                    }
                    self._save_to_queue(queue_item)

            print("[AWSUploader] Finished scanning existing captures")
        except Exception as e:
            print(f"[AWSUploader] Error scanning existing captures: {e}")

    def _background_sync(self):
        """Background thread that periodically processes the upload queue"""
        import time
        while True:
            try:
                time.sleep(30)  # Check every 30 seconds

                if not self._is_online():
                    continue

                queue_files = sorted(self.queue_dir.glob("queue_*.json"))
                if queue_files:
                    print(f"[AWSUploader] Processing {len(queue_files)} queued uploads...")

                    for queue_file in queue_files:
                        if not self._is_online():
                            print("[AWSUploader] Lost connection, pausing sync")
                            break

                        self._process_queue_item(queue_file)
                        time.sleep(1)  # Rate limiting

            except Exception as e:
                print(f"[AWSUploader] Background sync error: {e}")

    def get_queue_status(self) -> dict:
        """Get current queue status"""
        try:
            queue_files = list(self.queue_dir.glob("queue_*.json"))
            return {
                'online': self._is_online(),
                'queued_items': len(queue_files),
                'oldest_queued': min([f.stat().st_mtime for f in queue_files]) if queue_files else None
            }
        except Exception as e:
            print(f"[AWSUploader] Error getting queue status: {e}")
            return {'online': False, 'queued_items': 0, 'oldest_queued': None}

