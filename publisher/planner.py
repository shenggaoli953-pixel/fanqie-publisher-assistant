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
    publish_times = config.effective_publish_times

    def finish_day(over_limit: bool = False) -> None:
        nonlocal current_day, current_chapters, current_character_count
        if not current_chapters:
            return

        if len(publish_times) == 1:
            schedule.append(
                ScheduledDay(
                    publish_at=datetime.combine(current_day, publish_times[0]),
                    chapters=tuple(current_chapters),
                    over_limit=over_limit,
                )
            )
            current_day += timedelta(days=1)
            current_chapters = []
            current_character_count = 0
            return

        slot_counts = [0] * len(publish_times)
        chapter_count = len(current_chapters)
        for position, chapter in enumerate(current_chapters):
            slot_index = position * len(publish_times) // chapter_count
            publish_at = datetime.combine(
                current_day,
                publish_times[slot_index],
            ) + timedelta(minutes=slot_counts[slot_index])
            next_slot_time = (
                publish_times[slot_index + 1]
                if slot_index + 1 < len(publish_times)
                else None
            )
            if publish_at.date() != current_day or (
                next_slot_time is not None and publish_at.time() >= next_slot_time
            ):
                raise ValueError("选定的发布时间间隔不足，无法保持章节顺序")
            schedule.append(
                ScheduledDay(
                    publish_at=publish_at,
                    chapters=(chapter,),
                    over_limit=over_limit,
                )
            )
            slot_counts[slot_index] += 1

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
