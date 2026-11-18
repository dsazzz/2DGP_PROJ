"""프로젝트의 리소스 기준 경로. 실행한 작업 디렉터리에 의존하지 않는다."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ART_ROOT = PROJECT_ROOT / "art"
