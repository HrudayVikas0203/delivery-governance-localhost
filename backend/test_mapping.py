from app.core.config import get_settings
from app.ai.ppt_mapping import map_with_gemini
from app.ai.template_analysis import TemplateStructure, TemplateSlide, TemplateElement
import json

template = TemplateStructure(
    slide_width=1000,
    slide_height=1000,
    slide_count=1,
    slides=[
        TemplateSlide(
            slide_index=0,
            elements=[
                TemplateElement(id="slide_0_shape_0", type="shape", text="{{RISKS}}", width=500, height=500, char_limit_estimate=200)
            ]
        )
    ]
)

status_data = {
    "projects": [{"id": "1", "name": "Test Project"}],
    "weekly_statuses": [
        {"fields": {"risks": "Risk A"}},
        {"fields": {"risks": "Risk B"}}
    ]
}

try:
    result = map_with_gemini(template, status_data)
    print("Success:")
    print(result.model_dump_json())
except Exception as e:
    import traceback
    traceback.print_exc()
