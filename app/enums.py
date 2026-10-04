from enum import Enum


class Role(str, Enum):
    ATTENDEE = "attendee"
    ORGANIZER = "organizer"


class Category(str, Enum):
    CONCERT = "concert"
    WORKSHOP = "workshop"
    MEETUP = "meetup"
    CONFERENCE = "conference"


class EventStatus(str, Enum):
    PUBLISHED = "published"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class BookingStatus(str, Enum):
    CONFIRMED = "confirmed"
    CANCELLED_BY_USER = "cancelled_by_user"
    CANCELLED_BY_ORGANIZER = "cancelled_by_organizer"


class RefundStatus(str, Enum):
    NONE = "none"
    PENDING = "pending"