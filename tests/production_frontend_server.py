from app.local_web_app import create_app
from tests.visual_baseline_app import VisualBaselineService


app = create_app(
    service=VisualBaselineService(),
)
