from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import APP


def main() -> None:
    parser = argparse.ArgumentParser(description="用平台 AI 重新生成指定课程的文字内容与知识脉络")
    parser.add_argument("course_id")
    parser.add_argument("--learner-id", default="1001-1001")
    parser.add_argument("--minutes", type=int, default=5)
    parser.add_argument("--speakers", type=int, default=2)
    args = parser.parse_args()

    course = APP.courses.detail(args.learner_id, args.course_id)
    generated, mode = APP.ai.generate_demo_course(
        {
            "title": course["title"],
            "subject": course.get("subject") or "课程",
            "scene": course.get("scene") or "学校课堂",
        },
        duration_minutes=args.minutes,
        speaker_count=args.speakers,
    )
    updated = APP.courses.replace_course_content(
        args.learner_id,
        args.course_id,
        {
            **generated,
            "subject": course.get("subject"),
            "grade": course.get("grade"),
            "scene": course.get("scene"),
        },
    )
    review, review_mode = APP.ai.review(updated)
    APP.store.save_review(args.learner_id, args.course_id, review, review_mode)
    print(f"course_id={args.course_id} generation={mode} review={review_mode} segments={len(updated['segments'])}")


if __name__ == "__main__":
    main()
