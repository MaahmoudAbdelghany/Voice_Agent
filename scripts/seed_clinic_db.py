"""
Clinic Database Seeder Pipeline for Egyptian Polyclinics.

Populates the database with realistic Egyptian medical specialties,
doctors (consultants and specialists), shift schedules, and pricing.

Usage:
    python scripts/seed_clinic_db.py           # Idempotent upsert (preserves existing bookings)
    python scripts/seed_clinic_db.py --reset   # Wipes all tables and recreates from scratch
"""

import argparse
import asyncio
import logging
import sys
from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.config import get_settings
from src.db.models import Doctor, DoctorSchedule, Specialty
from src.db.session import close_db, get_async_session, get_engine, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("seed_clinic_db")


# ==============================================================================
# Seed Data Definitions
# ==============================================================================

SPECIALTIES_SEED = [
    {
        "code": "internal_medicine",
        "name_ar": "الباطنة والجهاز الهضمي",
        "name_en": "Internal Medicine & Gastroenterology",
        "description": "تشخيص وعلاج أمراض الباطنة العامة، الكبد، الجهاز الهضمي، ومتابعة السكري وارتفاع ضغط الدم.",
        "doctors": [
            {
                "name_ar": "د. أحمد محمود الشريف",
                "name_en": "Dr. Ahmed Mahmoud El-Sherif",
                "title": "consultant",
                "examination_fee": 350.0,
                "consultation_fee": 150.0,
                "schedules": [
                    {"day_of_week": 0, "start": time(18, 0), "end": time(22, 0), "capacity": 20},  # السبت
                    {"day_of_week": 2, "start": time(18, 0), "end": time(22, 0), "capacity": 20},  # الاثنين
                    {"day_of_week": 4, "start": time(18, 0), "end": time(22, 0), "capacity": 20},  # الأربعاء
                ],
            },
            {
                "name_ar": "د. مروة كمال الدين",
                "name_en": "Dr. Marwa Kamal El-Din",
                "title": "specialist",
                "examination_fee": 250.0,
                "consultation_fee": 100.0,
                "schedules": [
                    {"day_of_week": 1, "start": time(11, 0), "end": time(15, 0), "capacity": 15},  # الأحد
                    {"day_of_week": 3, "start": time(11, 0), "end": time(15, 0), "capacity": 15},  # الثلاثاء
                    {"day_of_week": 5, "start": time(11, 0), "end": time(15, 0), "capacity": 15},  # الخميس
                ],
            },
        ],
    },
    {
        "code": "pediatrics",
        "name_ar": "الأطفال وحديثي الولادة",
        "name_en": "Pediatrics & Neonatology",
        "description": "رعاية صحة ونمو الأطفال، فحص حديثي الولادة، جدول التطعيمات، وعلاج النزلات المعوية وحساسية الصدر.",
        "doctors": [
            {
                "name_ar": "د. حسام فاروق القاضي",
                "name_en": "Dr. Hossam Farouk El-Qadi",
                "title": "consultant",
                "examination_fee": 300.0,
                "consultation_fee": 150.0,
                "schedules": [
                    {"day_of_week": 0, "start": time(10, 0), "end": time(14, 0), "capacity": 20},  # السبت
                    {"day_of_week": 2, "start": time(10, 0), "end": time(14, 0), "capacity": 20},  # الاثنين
                    {"day_of_week": 4, "start": time(10, 0), "end": time(14, 0), "capacity": 20},  # الأربعاء
                ],
            },
            {
                "name_ar": "د. نهى عبد العزيز",
                "name_en": "Dr. Noha Abdel Aziz",
                "title": "specialist",
                "examination_fee": 220.0,
                "consultation_fee": 100.0,
                "schedules": [
                    {"day_of_week": 1, "start": time(17, 0), "end": time(21, 0), "capacity": 18},  # الأحد
                    {"day_of_week": 3, "start": time(17, 0), "end": time(21, 0), "capacity": 18},  # الثلاثاء
                    {"day_of_week": 5, "start": time(17, 0), "end": time(21, 0), "capacity": 18},  # الخميس
                ],
            },
        ],
    },
    {
        "code": "orthopedics",
        "name_ar": "العظام والمفاصل",
        "name_en": "Orthopedics & Joint Surgery",
        "description": "تشخيص وعلاج آلام المفاصل، العمود الفقري، خشونة الركبة، علاج الكسور، وإصابات الملاعب والأوتار.",
        "doctors": [
            {
                "name_ar": "د. طارق عبد الرحمن سليمان",
                "name_en": "Dr. Tarek Abdel Rahman Soliman",
                "title": "consultant",
                "examination_fee": 400.0,
                "consultation_fee": 200.0,
                "schedules": [
                    {"day_of_week": 0, "start": time(19, 0), "end": time(23, 0), "capacity": 16},  # السبت
                    {"day_of_week": 2, "start": time(19, 0), "end": time(23, 0), "capacity": 16},  # الاثنين
                    {"day_of_week": 4, "start": time(19, 0), "end": time(23, 0), "capacity": 16},  # الأربعاء
                ],
            },
            {
                "name_ar": "د. كريم سامي عز الدين",
                "name_en": "Dr. Karim Samy Ezz El-Din",
                "title": "specialist",
                "examination_fee": 260.0,
                "consultation_fee": 120.0,
                "schedules": [
                    {"day_of_week": 1, "start": time(12, 0), "end": time(16, 0), "capacity": 15},  # الأحد
                    {"day_of_week": 3, "start": time(12, 0), "end": time(16, 0), "capacity": 15},  # الثلاثاء
                    {"day_of_week": 5, "start": time(12, 0), "end": time(16, 0), "capacity": 15},  # الخميس
                ],
            },
        ],
    },
    {
        "code": "obstetrics_gynecology",
        "name_ar": "النساء والتوليد",
        "name_en": "Obstetrics & Gynecology",
        "description": "متابعة الحمل الحرج والطبيعي، الفحص بالسونار ثلاثي ورباعي الأبعاد، وعلاج اضطرابات الهرمونات وتأخر الإنجاب.",
        "doctors": [
            {
                "name_ar": "د. هالة مصطفى رضوان",
                "name_en": "Dr. Hala Mostafa Radwan",
                "title": "consultant",
                "examination_fee": 380.0,
                "consultation_fee": 180.0,
                "schedules": [
                    {"day_of_week": 0, "start": time(13, 0), "end": time(17, 0), "capacity": 15},  # السبت
                    {"day_of_week": 2, "start": time(13, 0), "end": time(17, 0), "capacity": 15},  # الاثنين
                    {"day_of_week": 4, "start": time(13, 0), "end": time(17, 0), "capacity": 15},  # الأربعاء
                ],
            },
            {
                "name_ar": "د. دينا صلاح الباجوري",
                "name_en": "Dr. Dina Salah El-Bagoury",
                "title": "specialist",
                "examination_fee": 270.0,
                "consultation_fee": 120.0,
                "schedules": [
                    {"day_of_week": 1, "start": time(18, 0), "end": time(22, 0), "capacity": 18},  # الأحد
                    {"day_of_week": 3, "start": time(18, 0), "end": time(22, 0), "capacity": 18},  # الثلاثاء
                    {"day_of_week": 5, "start": time(18, 0), "end": time(22, 0), "capacity": 18},  # الخميس
                ],
            },
        ],
    },
    {
        "code": "dentistry",
        "name_ar": "الأسنان وجراحة الفم",
        "name_en": "Dentistry & Oral Surgery",
        "description": "طب وجراحة الفم والأسنان، علاج الجذور وحشو العصب، تبييض وتنظيف الجير، وتركيبات الأسنان والزراعة.",
        "doctors": [
            {
                "name_ar": "د. عمرو خالد النجار",
                "name_en": "Dr. Amr Khaled El-Naggar",
                "title": "consultant",
                "examination_fee": 350.0,
                "consultation_fee": 150.0,
                "schedules": [
                    {"day_of_week": 0, "start": time(16, 0), "end": time(21, 0), "capacity": 14},  # السبت
                    {"day_of_week": 3, "start": time(16, 0), "end": time(21, 0), "capacity": 14},  # الثلاثاء
                    {"day_of_week": 5, "start": time(16, 0), "end": time(21, 0), "capacity": 14},  # الخميس
                ],
            },
            {
                "name_ar": "د. ياسمين عادل إبراهيم",
                "name_en": "Dr. Yasmine Adel Ibrahim",
                "title": "specialist",
                "examination_fee": 230.0,
                "consultation_fee": 100.0,
                "schedules": [
                    {"day_of_week": 1, "start": time(10, 0), "end": time(15, 0), "capacity": 12},  # الأحد
                    {"day_of_week": 2, "start": time(10, 0), "end": time(15, 0), "capacity": 12},  # الاثنين
                    {"day_of_week": 4, "start": time(10, 0), "end": time(15, 0), "capacity": 12},  # الأربعاء
                ],
            },
        ],
    },
]


# ==============================================================================
# Seeder Logic
# ==============================================================================

async def seed_clinic_database(reset: bool = False) -> dict[str, int]:
    """
    Seed or update clinic specialties, doctors, and schedules.

    Args:
        reset: If True, drops all existing tables and rebuilds fresh.
               If False, executes an idempotent upsert preserving bookings.

    Returns:
        Dictionary with count of specialties, doctors, and schedules seeded.
    """
    settings = get_settings()
    logger.info("Initializing database for clinic: '%s'", settings.clinic_name)
    logger.info("Database URL: %s", settings.database_url)

    engine = get_engine(settings.database_url)

    if reset:
        logger.warning("Reset flag detected: Dropping and recreating all tables...")
        await init_db(engine=engine, reset=True)
        logger.info("All tables recreated cleanly.")
    else:
        # Ensure tables exist
        await init_db(engine=engine, reset=False)

    counts = {"specialties": 0, "doctors": 0, "schedules": 0}

    async with get_async_session() as session:
        for spec_data in SPECIALTIES_SEED:
            # 1. Upsert Specialty
            stmt = (
                select(Specialty)
                .options(selectinload(Specialty.doctors))
                .where(Specialty.code == spec_data["code"])
            )
            res = await session.execute(stmt)
            specialty = res.scalars().first()

            if not specialty:
                specialty = Specialty(
                    code=spec_data["code"],
                    name_ar=spec_data["name_ar"],
                    name_en=spec_data["name_en"],
                    description=spec_data["description"],
                )
                session.add(specialty)
                await session.flush()
                logger.info("Created Specialty: %s (%s)", specialty.name_ar, specialty.code)
            else:
                specialty.name_ar = spec_data["name_ar"]
                specialty.name_en = spec_data["name_en"]
                specialty.description = spec_data["description"]
                await session.flush()

            counts["specialties"] += 1

            # 2. Upsert Doctors for this Specialty
            for doc_data in spec_data["doctors"]:
                doc_stmt = (
                    select(Doctor)
                    .options(selectinload(Doctor.schedules))
                    .where(
                        Doctor.specialty_id == specialty.id,
                        Doctor.name_ar == doc_data["name_ar"],
                    )
                )
                doc_res = await session.execute(doc_stmt)
                doctor = doc_res.scalars().first()

                if not doctor:
                    doctor = Doctor(
                        specialty_id=specialty.id,
                        name_ar=doc_data["name_ar"],
                        name_en=doc_data["name_en"],
                        title=doc_data["title"],
                        examination_fee=doc_data["examination_fee"],
                        consultation_fee=doc_data["consultation_fee"],
                        is_active=True,
                    )
                    session.add(doctor)
                    await session.flush()
                    logger.info("  Created Doctor: %s (%s)", doctor.name_ar, doctor.title)
                else:
                    doctor.title = doc_data["title"]
                    doctor.examination_fee = doc_data["examination_fee"]
                    doctor.consultation_fee = doc_data["consultation_fee"]
                    doctor.is_active = True
                    await session.flush()

                counts["doctors"] += 1

                # 3. Upsert Schedules for this Doctor
                for sched_data in doc_data["schedules"]:
                    sched_stmt = select(DoctorSchedule).where(
                        DoctorSchedule.doctor_id == doctor.id,
                        DoctorSchedule.day_of_week == sched_data["day_of_week"],
                        DoctorSchedule.start_time == sched_data["start"],
                    )
                    sched_res = await session.execute(sched_stmt)
                    schedule = sched_res.scalars().first()

                    if not schedule:
                        schedule = DoctorSchedule(
                            doctor_id=doctor.id,
                            day_of_week=sched_data["day_of_week"],
                            start_time=sched_data["start"],
                            end_time=sched_data["end"],
                            max_capacity=sched_data["capacity"],
                            is_active=True,
                        )
                        session.add(schedule)
                    else:
                        schedule.end_time = sched_data["end"]
                        schedule.max_capacity = sched_data["capacity"]
                        schedule.is_active = True

                    counts["schedules"] += 1

        await session.commit()

    logger.info(
        "Seeding completed successfully! Total: %d specialties, %d doctors, %d shift schedules.",
        counts["specialties"],
        counts["doctors"],
        counts["schedules"],
    )
    return counts


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed database for Egyptian Polyclinic Voice Agent."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate all database tables before seeding.",
    )
    args = parser.parse_args()

    try:
        counts = asyncio.run(seed_clinic_database(reset=args.reset))
        print("\n" + "=" * 60)
        print("  تم إدخال وتحديث بيانات العيادة بنجاح (Clinic Database Seeded)")
        print("=" * 60)
        print(f"  * الأقسام الطبية (Specialties) : {counts['specialties']}")
        print(f"  * الأطباء والاستشاريون (Doctors) : {counts['doctors']}")
        print(f"  * شفتات العمل الأسبوعية (Schedules): {counts['schedules']}")
        print("=" * 60 + "\n")
    except Exception:
        logger.exception("Seeding failed")
        sys.exit(1)
    finally:
        asyncio.run(close_db())


if __name__ == "__main__":
    main()
