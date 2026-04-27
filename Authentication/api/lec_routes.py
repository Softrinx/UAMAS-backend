"""
Blueprint for lecture-related API routes.
Created by: https://github.com/ByteBenders-compScientists/UAMAS-backend
Actions: 
- Add a new course
- Add units to a course
- Add students to a course
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from .models import db, User, Student, Lecturer, Unit, Course
from .utils import hashing_password, generate_join_code
import pandas as pd
import os
from sqlalchemy.orm import joinedload

# Create a blueprint for lecture routes
lec_blueprint = Blueprint('lectures', __name__)

'''
Only lecturers can call these routes
'''
@lec_blueprint.before_request
@jwt_required()
def check_lecturer():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    if user.role != 'lecturer':
        return jsonify({'error': 'Lecturer privileges required'}), 403
    claims = get_jwt()
    if claims["role"] != 'lecturer':
        return jsonify({'error': 'Lecturer privileges required'}), 403

# --- CRUD: Courses ---
@lec_blueprint.route('/courses', methods=['POST'])
def create_course():
    '''
    Create a new course.
    Requires: name, code, department, school
    Returns: JSON response with success message or error
    '''
    data = request.get_json() or {}
    # Validate required fields
    required_fields = ['name', 'code', 'department', 'school']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400
    
    # check existing course code if had been created by the user
    user_id = get_jwt_identity()
    existing_course = Course.query.filter_by(code=data['code'], created_by=user_id).first()
    if existing_course:
        return jsonify({'error': 'Course with this code already exists'}), 400
    # Create course
    course = Course(
        name=data['name'],
        code=data['code'],
        department=data['department'],
        school=data['school'],
        created_by=user_id
    )
    db.session.add(course)
    db.session.commit()
    return jsonify({'message': 'Course created successfully', 'course_id': course.id}), 201

@lec_blueprint.route('/courses', methods=['GET'])
def get_courses():
    '''
    Get all courses created by the lecturer.
    Returns: JSON response with list of courses
    '''
    user_id = get_jwt_identity()
    courses = Course.query.filter_by(created_by=user_id).all()
    return jsonify([course.to_dict() for course in courses]), 200

@lec_blueprint.route('/courses/<string:course_id>', methods=['GET'])
def get_course(course_id):
    '''
    Get a specific course by ID.
    Returns: JSON response with course details or error if not found
    '''
    course = Course.query.get(course_id)
    if not course:
        return jsonify({'error': 'Course not found'}), 404
    return jsonify(course.to_dict()), 200

@lec_blueprint.route('/courses/<string:course_id>', methods=['PUT'])
def update_course(course_id):
    '''
    Update a course.
    Requires: name, code, department, school
    Returns: JSON response with updated course details or error if not found
    '''
    course = Course.query.get(course_id)
    if not course:
        return jsonify({'error': 'Course not found'}), 404
    
    data = request.get_json() or {}
    for field in ['name', 'code', 'department', 'school']:
        if field in data:
            setattr(course, field, data[field])
    
    db.session.commit()
    return jsonify(course.to_dict()), 200

@lec_blueprint.route('/courses/<string:course_id>', methods=['DELETE'])
def delete_course(course_id):
    '''
    Delete a course.
    Returns: JSON response with success message or error if not found
    '''
    course = Course.query.get(course_id)
    if not course:
        return jsonify({'error': 'Course not found'}), 404
    
    db.session.delete(course)
    db.session.commit()
    return jsonify({'message': 'Course deleted successfully'}), 200

# --- CRUD: Units ---
@lec_blueprint.route('/units', methods=['POST'])
def create_unit():
    '''
    Create a new unit.
    Requires: unit_code, unit_name, level, semester, course_id
    Returns: JSON response with success message or error
    '''
    data = request.get_json() or {}
    
    # Validate required fields
    required_fields = ['unit_code', 'unit_name', 'level', 'semester', 'course_id']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400
    
    course = Course.query.get(data['course_id'])
    if not course:
        return jsonify({'error': 'Course not found'}), 404
    
    # Check if unit already exists
    existing_unit = Unit.query.filter_by(unit_code=data['unit_code'], course_id=course.id).first()
    if existing_unit:
        return jsonify({'error': 'Unit with this code already exists in the course'}), 400
    
    # Generate a unique join code for this unit
    join_code = None
    while True:
        candidate = generate_join_code()
        if not Unit.query.filter_by(unique_join_code=candidate).first():
            join_code = candidate
            break
    
    # Create unit
    unit = Unit(
        unit_code=data['unit_code'],
        unit_name=data['unit_name'],
        level=data['level'],
        semester=data['semester'],
        course=course,
        unique_join_code=join_code
    )
    db.session.add(unit)
    db.session.commit()
    return jsonify({'message': 'Unit created successfully', 'unit_id': unit.id}), 201

@lec_blueprint.route('/units', methods=['GET'])
def get_units():
    '''
    Get all units created by the lecturer.
    Returns: JSON response with list of units
    '''
    user_id = get_jwt_identity()
    # get all courses created by the lecturer
    courses = Course.query.filter_by(created_by=user_id).all()
    if not courses:
        # return jsonify({'error': 'No courses found for this lecturer'}), 404 -> bug: not handled in the frontend
        return [], 200 # no courses registered yet
    # get all units for those courses (using course IDs)
    course_ids = [course.id for course in courses]
    units = Unit.query.filter(Unit.course_id.in_(course_ids)).all()
    # if not units: -> bug for 404 in frontend not handled
    #     return jsonify({'error': 'No units found for the lecturer\'s courses'}), 404
    # Return units as a list of dictionaries
    return jsonify([unit.to_dict() for unit in units]), 200

@lec_blueprint.route('/units/<string:unit_id>', methods=['GET'])
def get_unit(unit_id):
    '''
    Get a specific unit by ID.
    Returns: JSON response with unit details or error if not found
    '''
    unit = Unit.query.get(unit_id)
    if not unit:
        return jsonify({'error': 'Unit not found'}), 404
    return jsonify(unit.to_dict()), 200

@lec_blueprint.route('/units/<string:unit_id>', methods=['PUT'])
def update_unit(unit_id):
    '''
    Update a unit.
    Requires: unit_code, unit_name, level, semester, course_id
    Returns: JSON response with updated unit details or error if not found
    '''
    unit = Unit.query.get(unit_id)
    if not unit:
        return jsonify({'error': 'Unit not found'}), 404
    
    data = request.get_json() or {}
    for field in ['unit_code', 'unit_name', 'level', 'semester', 'course_id']:
        if field in data:
            setattr(unit, field, data[field])
    
    db.session.commit()
    return jsonify(unit.to_dict()), 200

@lec_blueprint.route('/units/<string:unit_id>', methods=['DELETE'])
def delete_unit(unit_id):
    '''
    Delete a unit.
    Returns: JSON response with success message or error if not found
    '''
    unit = Unit.query.get(unit_id)
    if not unit:
        return jsonify({'error': 'Unit not found'}), 404
    
    db.session.delete(unit)
    db.session.commit()
    return jsonify({'message': 'Unit deleted successfully'}), 200

# --- CRUD: Students ---
@lec_blueprint.route('/students/<string:student_id>', methods=['GET'])
def get_student(student_id):
    """
    Get a specific student's details by ID.
    """
    student = (
        Student.query
               .options(joinedload(Student.units).joinedload(Unit.course))
               .get(student_id)
    )
    if not student:
        return jsonify({'error': 'Student not found'}), 404
    return jsonify(student.to_dict()), 200

@lec_blueprint.route('/students', methods=['GET'])
def get_students():
    """
    Get all students in any course created by the lecturer.
    """
    lecturer_id = get_jwt_identity()

    # Join through units and courses, filtering on courses.created_by
    students = (
        Student.query
               .join(Student.units)
               .join(Unit.course)
               .filter(Course.created_by == lecturer_id)
               .options(joinedload(Student.units).joinedload(Unit.course))
               .distinct()
               .all()
    )

    # If none, return empty list (200)
    return jsonify([s.to_dict() for s in students]), 200

@lec_blueprint.route('/students/unit/<string:unit_id>', methods=['GET'])
def get_students_in_unit(unit_id):
    """
    Get all students enrolled in a specific unit.
    """
    unit = Unit.query.get(unit_id)
    if not unit:
        return jsonify({'error': 'Unit not found'}), 404

    students = unit.students

    return jsonify([s.to_dict() for s in students]), 200
