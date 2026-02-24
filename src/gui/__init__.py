from pathlib import Path

VERSION = "v1.0.0"

PROJECT_DIR = Path(__file__).parent.parent.parent.resolve()
QML_DIR = PROJECT_DIR / "qml"

CAPTURES_DIRNAME = "captures"
MACHINE_ID_FILENAME = "machine_id.txt"
PENDING_RECYCLES_FILENAME = "pending_recycles.json"
MLMODEL_PREDICTIONS_FILENAME = "mlmodel_predictions.csv"
