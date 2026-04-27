from . import db
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import foreign

from sqlalchemy.dialects.postgresql import JSONB

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum('student', 'lecturer', name='user_roles'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # one-to-one relations
    student = db.relationship('Student', uselist=False, back_populates='user', cascade='all, delete')
    lecturer = db.relationship('Lecturer', uselist=False, back_populates='user', cascade='all, delete')

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'role': self.role,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

    def __repr__(self):
        return f"<User {self.email}>"

# association table for students and units
student_units = db.Table(
    'student_units',
    db.Column('student_id', db.String(36),
              db.ForeignKey('students.id', ondelete='CASCADE'),
              primary_key=True),
    db.Column('unit_id', db.String(36),
              db.ForeignKey('units.id', ondelete='CASCADE'),
              primary_key=True),
)

class Student(db.Model):
    __tablename__ = 'students'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        unique=True
    )
    reg_number   = db.Column(db.String(30), unique=True, nullable=False)
    firstname     = db.Column(db.String(50), nullable=False)
    surname       = db.Column(db.String(50), nullable=False)
    othernames    = db.Column(db.String(50))
    # hobbies       = db.Column(db.JSON, default=list)
    hobbies = db.Column(JSONB, default=list)

    # student relates directly to units
    units = db.relationship(
        'Unit',
        secondary=student_units,
        back_populates='students',
        lazy='joined'
    )

    user = db.relationship('User', back_populates='student')

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'reg_number': self.reg_number,
            'firstname': self.firstname,
            'surname': self.surname,
            'othernames': self.othernames,
            'hobbies': self.hobbies,
            'units': [u.to_dict() for u in self.units]
        }

    def __repr__(self):
        return f"<Student {self.reg_number}>"

class Lecturer(db.Model):
    __tablename__ = 'lecturers'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        unique=True
    )
    firstname = db.Column(db.String(50), nullable=False)
    surname = db.Column(db.String(50), nullable=False)
    othernames = db.Column(db.String(50))

    # relationship
    user = db.relationship('User', back_populates='lecturer')
    courses = db.relationship('Course',
                              primaryjoin='Lecturer.user_id == foreign(Course.created_by)',
                              cascade='all, delete')

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'firstname': self.firstname,
            'surname': self.surname,
            'othernames': self.othernames,
            'courses': [course.to_dict() for course in self.courses]
        }

    def __repr__(self):
        return f"<Lecturer {self.firstname} {self.surname}>"

class Course(db.Model):
    __tablename__ = 'courses'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    school = db.Column(db.String(100), nullable=False)

    # course created by which lecturer
    created_by = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=False
    )

    # relationships
    units = db.relationship('Unit', back_populates='course', cascade='all, delete')

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'department': self.department,
            'school': self.school,
            'units': [u.to_dict() for u in self.units]
        }

    def __repr__(self):
        return f"<Course {self.code}>"

class Unit(db.Model):
    __tablename__ = 'units'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    unit_code = db.Column(db.String(20), nullable=False)
    unit_name = db.Column(db.String(100), nullable=False)
    level = db.Column(db.SmallInteger, nullable=False)
    semester = db.Column(db.SmallInteger, nullable=False)
    course_id = db.Column(
        db.String(36),
        db.ForeignKey('courses.id', ondelete='SET NULL')
    )
    unique_join_code = db.Column(db.String(50), unique=True, nullable=False)

    # relationships
    course = db.relationship('Course', back_populates='units')
    students = db.relationship(
        'Student',
        secondary=student_units,
        back_populates='units',
        lazy='joined'
    )

    def to_dict(self):
        return {
            'id': self.id,
            'unit_code': self.unit_code,
            'unit_name': self.unit_name,
            'level': self.level,
            'semester': self.semester,
            'course_id': self.course_id,
            'unique_join_code': self.unique_join_code
        }

    def __repr__(self):
        return f"<Unit {self.unit_code}>"


class EmailVerification(db.Model):
    __tablename__ = 'email_verifications'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(120), nullable=False, index=True)
    role = db.Column(db.Enum('student', 'lecturer', name='verification_roles'), nullable=False)
    code = db.Column(db.String(10), nullable=False)
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)

    def __repr__(self):
        return f"<EmailVerification {self.email} {self.role}>"
