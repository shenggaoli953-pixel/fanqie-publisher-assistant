from datetime import date, datetime, timedelta

from publisher.models import BookConfig, Chapter, PublishMode, ScheduledDay


def build_schedule(
    chapters: list[Chapter],
    config: BookConfig,
    start_date: date,
) -> list[ScheduledDay]:
    schedule: list[ScheduledDay] = []
    current_day = start_date
    current_chapters: list[Chapter] = []
    current_character_count = 0

    def finish_day(over_limit: bool = False) -> None:
        nonlocal current_day, current_chapters, current_character_count
        if not current_chapters:
            return
        schedule.append(
            ScheduledDay(
                publish_at=datetime.combine(current_day, config.publish_time),
                chapters=tuple(current_chapters),
                over_limit=over_limit,
            )
        )
        current_day += timedelta(days=1)
        current_chapters = []
        current_character_count = 0

    for chapter in sorted(chapters, key=lambda item: item.number):
        if config.mode is PublishMode.CHAPTERS:
            current_chapters.append(chapter)
            if len(current_chapters) == config.limit:
                finish_day()
            continue

        if not current_chapters and chapter.character_count > config.limit:
            current_chapters.append(chapter)
            finish_day(over_limit=True)
            continue
        if current_chapters and current_character_count + chapter.character_count > config.limit:
            finish_day()
        current_chapters.append(chapter)
        current_character_count += chapter.character_count

    finish_day()
    return schedule
