"""
Blueprint for Lecture-Assessments API routes.
Created by: https://github.com/ByteBenders-compScientists/UAMAS-backend
Actions:
- Create assessment(CAT, Case Study, Assignment): Manually or through AI
- Using AI to generate questions for assessments (Type topic, description, and number of questions etc) OR (Upload a document and AI will generate questions based on the content)
- Create questions manually
- Verify assessment questions and answers created by AI
- View and verify marked assessments by AI
- Update, delete, and view assessments
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import logging

from api import db
from api.utils import ai_create_assessment, ai_create_assessment_from_pdf, ALLOWED_QUESTION_TYPES
from api.models import Assessment, Question, Submission, Answer, Result, TotalMarks, Course, Unit, Notes, Lecturer, Student, User
from sqlalchemy.orm import joinedload

import os
import uuid
import json
import re
import os
import pandas as pd
from io import BytesIO

load_dotenv()
lec_blueprint = Blueprint('lec', __name__)

'''
Before every request to verify if the user is a lecturer
'''
@lec_blueprint.before_request
@jwt_required(locations=['cookies', 'headers'])
def verify_lecturer():
    user_id = get_jwt_identity()
    claims = get_jwt()
    if claims.get('role') != 'lecturer':
        return jsonify({'error': 'Unauthorized access'}), 403

@lec_blueprint.route('/ai/generate-assessments', methods=['POST'])
def generate_assessments():
    """
    Generate an assessment using AI based on the provided parameters.
    This endpoint is accessible only to lecturers.
    """
    user_id = get_jwt_identity()
    
    data = json.loads(request.form.get('payload', '{}'))

    required_fields = [
        'title', 'description','week', 'type', 'unit_id',
        'questions_type', 'topic', 'total_marks',
        'difficulty', 'number_of_questions', 'blooms_level'
    ]
    
    unit = Unit.query.get(data['unit_id'])
    if not unit:
        return jsonify({'message': 'Unit not found.'}), 404

    data['course_id'] = unit.course_id
    data['unit_name'] = unit.unit_name

    # Normalize optional fields; missing or empty strings become None
    for optional_key in ('deadline', 'duration', 'blooms_level', 'schedule_date'):
        if data.get(optional_key) in (None, ""):
            data[optional_key] = None

    # normalize questions_type to a list of strings
    questions_type = data.get('questions_type', [])
    if isinstance(questions_type, str):
        questions_type = [questions_type]
    if not isinstance(questions_type, (list, tuple)):
        return jsonify({'message': 'questions_type must be a list of strings.'}), 400
    questions_type = [str(qt).strip() for qt in questions_type if str(qt).strip()]
    if not questions_type:
        return jsonify({'message': 'At least one questions_type value is required.'}), 400
    invalid = [qt for qt in questions_type if qt not in ALLOWED_QUESTION_TYPES]
    if invalid:
        return jsonify({'message': f"Invalid questions_type values: {invalid}. Allowed: {ALLOWED_QUESTION_TYPES}"}), 400
    data['questions_type'] = questions_type

    # Validate required fields are present and not empty
    if not all(field in data and data[field] != "" for field in required_fields):
        return jsonify({'message': 'Invalid input data.'}), 400
    
    doc_file = request.files.get('doc')
    if doc_file:
        if not doc_file.filename.lower().endswith('.pdf'):
            return jsonify({
                'message': 'Only PDF files are supported. Please upload a PDF file.',
                'error_type': 'unsupported_format',
                'supported_formats': ['PDF'],
                'recommendation': 'Convert your file to PDF format before uploading.'
            }), 400

        ai_pdf_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'ai_pdf')
        if not os.path.exists(ai_pdf_dir):
            os.makedirs(ai_pdf_dir)
        
        pdf_filename = f"{uuid.uuid4()}.pdf"
        pdf_path = os.path.join(ai_pdf_dir, pdf_filename)
        
        doc_file.save(pdf_path)

        data['doc_file'] = pdf_path

        res = ai_create_assessment_from_pdf(data, pdf_path)

    else:
        res = ai_create_assessment(data)

    generated = res

    # if not hasattr(res, "choices") or len(res.choices) == 0:
    #     return jsonify({'message': 'No response from AI model.'}), 500

    # first_choice = res.choices[0]
    # if not (hasattr(first_choice, "message") and hasattr(first_choice.message, "content")):
    #     return jsonify({'message': 'Invalid response format from AI model.'}), 500

    # generated = first_choice.message.content

    # generated = re.sub(r'```json\s*', '', generated)
    # generated = re.sub(r'\s*```', '', generated)

    # try:
    #     payload = json.loads(generated)
    # except json.JSONDecodeError:
    #     return jsonify({'message': 'AI did not return valid JSON.'}), 500
    if not generated or not generated.strip():
        return jsonify({'message': 'No response from AI model.'}), 500

    # Strip markdown fences
    generated = generated.strip()
    generated = re.sub(r'^```(?:json)?\s*', '', generated)
    generated = re.sub(r'\s*```$', '', generated)
    
    try:
        payload = json.loads(generated)
    except json.JSONDecodeError as e:
        current_app.logger.error("AI JSON error: %s", generated)
        return jsonify({'message': 'AI did not return valid JSON.'}), 500

    assessment = Assessment(
        creator_id       = user_id,
        title            = data['title'],
        week             = data['week'],  # Default to week 1 if not provided
        description      = data['description'],
        questions_type   = data['questions_type'],
        type             = data['type'],
        unit_id          = data['unit_id'],
        course_id        = data['course_id'],
        topic            = data['topic'],
        total_marks      = data['total_marks'],
        difficulty       = data['difficulty'],
        number_of_questions = data['number_of_questions'],
        schedule_date    = data.get('schedule_date', None),  # Optional field
        deadline         = data.get('deadline', None),  # Optional field
        duration         = data.get('duration', None),  # Optional field
        blooms_level     = data.get('blooms_level', None)  # Optional field
    )
    db.session.add(assessment)
    db.session.flush()   # so that assessment.id is set

    for q_obj in payload:
        q_type = q_obj.get('type')
        if q_type not in ALLOWED_QUESTION_TYPES:
            return jsonify({'message': f"Invalid question type '{q_type}'. Allowed: {ALLOWED_QUESTION_TYPES}"}), 400

        choices = q_obj.get('choices')
        needs_choices = q_type != 'open-ended'

        if needs_choices and (choices is None or choices == []):
            return jsonify({'message': f"choices are required for question type '{q_type}'"}), 400
        if not needs_choices:
            choices = None

        question = Question(
            assessment_id = assessment.id,
            text          = q_obj.get('text'),
            marks         = float(q_obj.get('marks', 0)),
            type          = q_type,
            rubric        = q_obj.get('rubric'),
            correct_answer= q_obj.get('correct_answer'),
            choices       = choices
        )
        db.session.add(question)

    db.session.commit()

    return jsonify({
        'message'       : 'Assessment generated successfully.',
        'assessment_id' : assessment.id,
        'title'         : assessment.title
    }), 201


@lec_blueprint.route('/assessments/<assessment_id>/verify', methods=['GET'])
def verify_assessment(assessment_id):
    """
    Verify an assessment created by AI.
    This endpoint is accessible only to lecturers.
    """
    assessment = Assessment.query.get(assessment_id)
    if not assessment:
        return jsonify({'message': 'Assessment not found.'}), 404
    
    # Check if the assessment is already verified
    if assessment.verified:
        return jsonify({'message': 'Assessment is already verified.'}), 400
    
    # Mark the assessment as verified
    assessment.verified = True
    db.session.commit()

    return jsonify({
        'message': 'Assessment verified successfully.',
        'assessment_id': assessment.id,
        'title': assessment.title
    }), 200

@lec_blueprint.route('/generate-assessments', methods=['POST'])
def create_assessment():
    """
    Create an assessment manually.
    This endpoint is accessible only to lecturers.
    """
    user_id = get_jwt_identity()

    data = request.json or {}
    required_fields = [
        'title', 'description', 'week', 'type', 'unit_id',
        'questions_type', 'topic', 'total_marks',
        'difficulty', 'number_of_questions', 'blooms_level'
    ]
    if not all(field in data for field in required_fields):
        return jsonify({'message': 'Invalid input data.'}), 400
    
    # get course_id and unit_id from the payload
    unit = Unit.query.get(data['unit_id'])
    data['course_id'] = unit.course_id

    # optional set to None if = not provided or ""
    # if data['deadline'] == "":
    #     data['deadline'] = None
    # if data['duration'] == "":
    #     data['duration'] = None
    # if data['blooms_level'] == "":
    #     data['blooms_level'] = None
    # if data['schedule_date'] == "":
    #     data['schedule_date'] = None

    for optional_key in ('deadline', 'duration', 'blooms_level', 'schedule_date'):
        if data.get(optional_key) in (None, ""):
            data[optional_key] = None

    questions_type = data.get('questions_type', [])
    if isinstance(questions_type, str):
        questions_type = [questions_type]
    if not isinstance(questions_type, (list, tuple)):
        return jsonify({'message': 'questions_type must be a list of strings.'}), 400
    questions_type = [str(qt).strip() for qt in questions_type if str(qt).strip()]
    if not questions_type:
        return jsonify({'message': 'At least one questions_type value is required.'}), 400
    invalid = [qt for qt in questions_type if qt not in ALLOWED_QUESTION_TYPES]
    if invalid:
        return jsonify({'message': f"Invalid questions_type values: {invalid}. Allowed: {ALLOWED_QUESTION_TYPES}"}), 400
    data['questions_type'] = questions_type

    assessment = Assessment(
        creator_id       = user_id,
        title            = data['title'],
        week             = data['week'],  # Default to week 1 if not provided
        description      = data['description'],
        questions_type   = data['questions_type'],
        type             = data['type'],
        unit_id          = data['unit_id'],
        course_id        = data.get('course_id'),
        topic            = data['topic'],
        total_marks      = data['total_marks'],
        difficulty       = data['difficulty'],
        number_of_questions = data['number_of_questions'],
        schedule_date    = data.get('schedule_date', None),  # Optional field
        deadline         = data.get('deadline', None),  # Optional field
        duration         = data.get('duration', None),  # Optional field
        blooms_level     = data.get('blooms_level', None)  # Optional field
    )
    db.session.add(assessment)
    db.session.commit()

    # TODO: Add email notification to the target students about the created assessment
    
    return jsonify({
        'message': 'Assessment created successfully.',
        'assessment_id': assessment.id,
        'title': assessment.title
    }), 201

@lec_blueprint.route('/assessments/<assessment_id>', methods=['DELETE'])
def delete_assessment(assessment_id):
    """
    Delete an assessment.
    This endpoint is accessible only to lecturers.
    """
    assessment = Assessment.query.get(assessment_id)
    if not assessment:
        return jsonify({'message': 'Assessment not found.'}), 404
    
    db.session.delete(assessment)
    db.session.commit()

    return jsonify({'message': 'Assessment deleted successfully.'}), 200

@lec_blueprint.route('/assessments/<assessment_id>/questions', methods=['POST'])
def add_question_to_assessment(assessment_id):
    """
    Add a question to an assessment.
    This endpoint is accessible only to lecturers.
    """
    assessment = Assessment.query.get(assessment_id)
    if not assessment:
        return jsonify({'message': 'Assessment not found.'}), 404
    
    data = request.json or {}
    required_fields = ['text', 'marks', 'type', 'rubric', 'correct_answer']
    if not all(field in data for field in required_fields):
        return jsonify({'message': 'Invalid input data.'}), 400
    
    # set to none if not provided or ""
    if data['choices'] == "":
        data['choices'] = None
    if data["correct_answer"] == "":
        data['correct_answer'] = None
    
    question = Question(
        assessment_id = assessment.id,
        text          = data['text'],
        marks         = float(data['marks']),
        type          = data['type'],  # 'open-ended' or 'close-ended'
        rubric        = data['rubric'],
        correct_answer= data['correct_answer'],
        choices       = data.get('choices', [])  # Optional field for close-ended questions
    )
    
    db.session.add(question)
    db.session.commit()

    return jsonify({
        'message': 'Question added successfully.',
        'question_id': question.id
    }), 201

@lec_blueprint.route('/assessments', methods=['GET'])
def get_lecturer_assessments():
    '''
    Get all assessments created by the lecturer.
    This endpoint is accessible only to lecturers.
    '''
    user_id = get_jwt_identity()
    assessments = Assessment.query.filter_by(creator_id=user_id).all()
    return jsonify([assessment.to_dict() for assessment in assessments]), 200

@lec_blueprint.route('/submissions/assessments/<assessment_id>', methods=['GET'])
def get_assessment_submissions(assessment_id):
    """
    Get all submissions for all students.
    This endpoint returns all submissions made by the student, including completed and in-progress ones.
    """
    user_id = get_jwt_identity()
    logger = logging.getLogger(__name__)
    logger.info(f"[GET_ASSESSMENT_SUBMISSIONS] Fetching submissions - Assessment: {assessment_id}, Lecturer: {user_id}")

    submissions_data = []

    # assessments created by the lecturer and are verified
    assessment = Assessment.query.get(assessment_id)
    if not assessment:
        logger.warning(f"[GET_ASSESSMENT_SUBMISSIONS] Assessment not found - Assessment: {assessment_id}")
        return jsonify({'message': 'Assessment not found.'}), 404

    # iterate through all assessments and get submissions for each assessment
    submissions = Submission.query.filter_by(assessment_id=assessment.id).all()
    logger.info(f"[GET_ASSESSMENT_SUBMISSIONS] Found {len(submissions)} submissions - Assessment: {assessment_id}")
    
    for submission in submissions:
        submission_data = {
            'submission_id': submission.id,
            'assessment_id': submission.assessment_id,
            'student_id': submission.student_id,
            'graded': submission.graded
        }
        submissions_data.append(submission_data)
    # add the totalmarks for each submission and student name and registration number
    for submission in submissions_data:
        total_marks = TotalMarks.query.filter_by(submission_id=submission['submission_id']).first()
        submission['total_marks'] = total_marks.total_marks if total_marks else 0
        user = User.query.get(submission['student_id'])
        if user:
            student = Student.query.filter_by(user_id=user.id).first()
            if student:
                submission['student_name'] = student.firstname + ' ' + student.surname
                submission['reg_number'] = student.reg_number
        # get assessment topic, course name, and unit name
        assessment = Assessment.query.get(submission['assessment_id'])
        if assessment:
            submission['assessment_topic'] = assessment.topic
            course = Course.query.get(assessment.course_id)
            unit = Unit.query.get(assessment.unit_id)
            if course:
                submission['course_name'] = course.name
            else:
                submission['course_name'] = 'Unknown Course'
            if unit:
                submission['unit_name'] = unit.unit_name
            if unit:
                submission['unit_name'] = unit.unit_name
            else:
                submission['unit_name'] = 'Unknown Unit'

    # combine the submissions with their results
    for submission in submissions_data:
        logger.info(f"[GET_ASSESSMENT_SUBMISSIONS] Fetching results - Submission: {submission['submission_id']}, Student: {submission['student_id']}")
        results = Result.query.options(joinedload(Result.answer)).filter_by(assessment_id=submission['assessment_id'], student_id=submission['student_id']).all()
        logger.info(f"[GET_ASSESSMENT_SUBMISSIONS] Found {len(results)} results - Submission: {submission['submission_id']}")
        
        submission['results'] = []
        for result in results:
            result_dict = result.to_dict()
            logger.debug(f"[GET_ASSESSMENT_SUBMISSIONS] Processing result - Result ID: {result.id}, Has Answer: {result.answer is not None}, Has Image: {result.answer.image_path if result.answer else 'None'}")
            question = Question.query.get(result_dict['question_id'])
            if question:
                result_dict['question_text'] = question.text
                result_dict['marks'] = question.marks
            else:
                result_dict['question_text'] = 'Unknown Question'
            submission['results'].append(result_dict)

    return jsonify(submissions_data), 200

@lec_blueprint.route('/submissions/student/<student_id>', methods=['GET'])
def get_student_submissions(student_id):
    """
    Get all submissions made by a specific student.
    This endpoint returns all submissions made by the student, including completed and in-progress ones.
    """
    user_id = get_jwt_identity()
    logger = logging.getLogger(__name__)
    logger.info(f"[GET_STUDENT_SUBMISSIONS] Fetching student submissions - Student: {student_id}, Lecturer: {user_id}")

    submissions_data = []

    # Get all submissions for the specified student
    submissions = Submission.query.filter_by(student_id=student_id).all()
    logger.info(f"[GET_STUDENT_SUBMISSIONS] Found {len(submissions)} submissions - Student: {student_id}")
    
    for submission in submissions:
        submission_data = {
            'submission_id': submission.id,
            'assessment_id': submission.assessment_id,
            'student_id': submission.student_id,
            'graded': submission.graded
        }
        submissions_data.append(submission_data)
    # Add the total marks for each submission
    for submission in submissions_data:
        total_marks = TotalMarks.query.filter_by(submission_id=submission['submission_id']).first()
        submission['total_marks'] = total_marks.total_marks if total_marks else 0
    # Combine the submissions with their results
    for submission in submissions_data:
        logger.info(f"[GET_STUDENT_SUBMISSIONS] Fetching results - Submission: {submission['submission_id']}, Student: {student_id}")
        results = Result.query.options(joinedload(Result.answer)).filter_by(assessment_id=submission['assessment_id'], student_id=submission['student_id']).all()
        logger.info(f"[GET_STUDENT_SUBMISSIONS] Found {len(results)} results - Submission: {submission['submission_id']}")
        
        submission['results'] = []
        for result in results:
            result_dict = result.to_dict()
            logger.debug(f"[GET_STUDENT_SUBMISSIONS] Processing result - Result ID: {result.id}, Has Answer: {result.answer is not None}, Has Image: {result.answer.image_path if result.answer else 'None'}")
            question = Question.query.get(result_dict['question_id'])
            if question:
                result_dict['question_text'] = question.text
                result_dict['marks'] = question.marks
            else:
                result_dict['question_text'] = 'Unknown Question'
            submission['results'].append(result_dict)
    return jsonify(submissions_data), 200

@lec_blueprint.route('/submissions/<submission_id>', methods=['PUT'])
def update_submission(submission_id):
    """
    Update a submission's grading status and total marks.
    This endpoint is accessible only to lecturers.
    """
    user_id = get_jwt_identity()
    
    # Get submission from database
    submission = Submission.query.get(submission_id)
    if not submission:
        return jsonify({'message': 'Submission not found.'}), 404
    
    data = request.json or {}
    
    # Validate input data
    if 'feedback' not in data or 'score' not in data or 'question_id' not in data:
        return jsonify({'message': 'Invalid input data.'}), 400
    
    # Update total marks: Recompute the total marks for the submission and update total_marks table
    # Calculate total marks in Python 
    results = Result.query.filter_by(
        student_id=submission.student_id,
        assessment_id=submission.assessment_id
    ).all()

    result = Result.query.filter_by(
        question_id=data['question_id'],
        student_id=submission.student_id,
        assessment_id=submission.assessment_id
    ).first()

    # Update the result with new marks and feedback
    result.score = float(data['score'])
    result.feedback = data['feedback']
    db.session.add(result)
    db.session.commit()

    total_marks = 0.0
    for result in results:
        # Check if score is a dict with 'marks_awarded' key, or just a float/number 
        if result.score:
            if isinstance(result.score, dict) and 'marks_awarded' in result.score:
                total_marks += float(result.score['marks_awarded'])
            elif isinstance(result.score, (int, float)):
                # If score is already a number, use it directly
                total_marks += float(result.score)
            else:
                # Handle other cases - log for debugging
                print(f"Unexpected score format: {type(result.score)} - {result.score}")

    # Update total marks in the database
    total_marks_entry = TotalMarks.query.filter_by(submission_id=submission.id).first()
    total_marks_entry.total_marks = total_marks
    
    db.session.add(total_marks_entry)
    db.session.commit()
    
    return jsonify({
        'message': 'Submission updated successfully.',
        'submission_id': submission.id,
        'graded': submission.graded,
        'total_marks': total_marks_entry.total_marks
    }), 200

@lec_blueprint.route('/submissions/units/<unit_id>/download', methods=['GET'])
def download_submissions(unit_id):
    """
    Download all submissions for a specific unit in excel file.
    Submission contain:- id, assessment_id, student_id, submitted_at, graded
    From unit_id, get course_id (name) and unit_name AND fetch all assessment_ids for that unit.
    For each assessment_id, get all submissions and their results.
    Each submission contains:- id, assessment_id, student_id, submitted_at, graded
    Results are in TotalMarks table, which contains:- submission_id, total_marks
    From student_id(user_id), get student name and reg_number.

    Returns excel file with all submissions for the unit.
    This endpoint is accessible only to lecturers.
    """
    user_id = get_jwt_identity()
    
    # Get unit and course information
    unit = Unit.query.get(unit_id)
    if not unit:
        return jsonify({'message': 'Unit not found.'}), 404
    
    course = Course.query.get(unit.course_id)
    if not course:
        return jsonify({'message': 'Course not found.'}), 404
    
    # Fetch all assessments for the unit
    assessments = Assessment.query.filter_by(unit_id=unit_id).all()
    
    submissions_data = []
    
    for assessment in assessments:
        submissions = Submission.query.filter_by(assessment_id=assessment.id).all()
        for submission in submissions:
            total_marks_entry = TotalMarks.query.filter_by(submission_id=submission.id).first()
            total_marks = total_marks_entry.total_marks if total_marks_entry else 0
            
            student = Student.query.filter_by(user_id=submission.student_id).first()
            if student:
                student_name = f"{student.firstname} {student.surname}"
                reg_number = student.reg_number
            else:
                student_name = 'Unknown Student'
                reg_number = 'N/A'
            
            submission_data = {
                'submission_id': submission.id,
                'assessment_topic': assessment.topic,
                'student_name': student_name,
                'reg_number': reg_number,
                'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None,
                'graded': submission.graded,
                'total_marks': total_marks,
                'out_of': assessment.total_marks
            }
            submissions_data.append(submission_data)

    # Create an Excel file with the submissions data

    df = pd.DataFrame(submissions_data)
    
    # Create a BytesIO object to hold the Excel file in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Submissions')
        # Add metadata about the course and unit
        workbook = writer.book
        worksheet = writer.sheets['Submissions']
        worksheet.write('A1', f'Course: {course.name}, Unit: {unit.unit_name}')

    output.seek(0)
    
    return current_app.response_class(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={
            'Content-Disposition': f'attachment; filename=submissions_{unit_id}.xlsx'
        }
    )

@lec_blueprint.route('/submissions/assessments/<assessment_id>/download', methods=['GET'])
def download_assessment_submissions(assessment_id):
    """
    Download all submissions for a specific assessment in excel file.
    Submission contain:- id, assessment_id, student_id, submitted_at, graded
    From assessment_id, get course_id (name) and unit_name AND fetch all submissions and their results.
    Each submission contains:- id, assessment_id, student_id, submitted_at, graded
    Results are in TotalMarks table, which contains:- submission_id, total_marks
    From student_id(user_id), get student name and reg_number.

    Returns excel file with all submissions for the assessment.
    This endpoint is accessible only to lecturers.
    """
    user_id = get_jwt_identity()
    
    # Get assessment information
    assessment = Assessment.query.get(assessment_id)
    if not assessment:
        return jsonify({'message': 'Assessment not found.'}), 404
    
    unit = Unit.query.get(assessment.unit_id)
    if not unit:
        return jsonify({'message': 'Unit not found.'}), 404
    
    course = Course.query.get(assessment.course_id)
    if not course:
        return jsonify({'message': 'Course not found.'}), 404
    
    submissions_data = []
    
    # Fetch all submissions for the assessment
    submissions = Submission.query.filter_by(assessment_id=assessment.id).all()
    for submission in submissions:
        total_marks_entry = TotalMarks.query.filter_by(submission_id=submission.id).first()
        total_marks = total_marks_entry.total_marks if total_marks_entry else 0
        
        student = Student.query.filter_by(user_id=submission.student_id).first()
        if student:
            student_name = f"{student.firstname} {student.surname}"
            reg_number = student.reg_number
        else:
            student_name = 'Unknown Student'
            reg_number = 'N/A'
        
        submission_data = {
            'submission_id': submission.id,
            'assessment_topic': assessment.topic,
            'student_name': student_name,
            'reg_number': reg_number,
            'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None,
            'graded': submission.graded,
            'total_marks': total_marks,
            'out_of': assessment.total_marks
        }
        submissions_data.append(submission_data)

    # Create an Excel file with the submissions data
    df = pd.DataFrame(submissions_data)
    
    # Create a BytesIO object to hold the Excel file in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Submissions')
        # Add metadata about the course and unit
        workbook = writer.book
        worksheet = writer.sheets['Submissions']
        worksheet.write('A1', f'Course: {course.name}, Unit: {unit.unit_name}')

    output.seek(0)
    
    return current_app.response_class(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={
            'Content-Disposition': f'attachment; filename=submissions_{assessment_id}.xlsx'
        }
    )

@lec_blueprint.route('/units/<unit_id>/notes', methods=['POST'])
def upload_notes(unit_id):
    """
    Upload notes for a specific unit.
    """
    user_id = get_jwt_identity()

    # Get course_id from the unit
    unit = Unit.query.get(unit_id)
    if not unit:
        return jsonify({'message': 'Unit not found.'}), 404
    course_id = unit.course_id
    
    # Check if file is present in request
    if 'file' not in request.files:
        return jsonify({'message': 'No file provided.'}), 400
    
    file = request.files['file']
    
    # Check if file is selected
    if file.filename == '':
        return jsonify({'message': 'No file selected.'}), 400
    
    # Get additional form data
    title = request.form.get('title')
    description = request.form.get('description', '')
    
    if not title:
        return jsonify({'message': 'Title is required.'}), 400
    
    # Define allowed file extensions - only PDF now
    ALLOWED_EXTENSIONS = {
        'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'doc': 'application/msword',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'ppt': 'application/vnd.ms-powerpoint',
        'txt': 'text/plain',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'xls': 'application/vnd.ms-excel',
        'mp3': 'audio/mpeg',
        'mp4': 'video/mp4',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'csv': 'text/csv',
        'zip': 'application/zip'
    }
    
    def allowed_file(filename):
        return '.' in filename and \
               filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS.keys()
    
    if not allowed_file(file.filename):
        return jsonify({
            'message': 'Invalid file type. Only PDF files are allowed.'
        }), 400
    
    try:
        # Create secure filename
        original_filename = secure_filename(file.filename)
        file_extension = original_filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{uuid.uuid4()}_{original_filename}"
        
        # Create notes directory structure
        notes_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'notes')
        course_dir = os.path.join(notes_dir, f"course_{course_id}")
        unit_dir = os.path.join(course_dir, f"unit_{unit_id}")
        
        # Create directories if they don't exist
        os.makedirs(unit_dir, exist_ok=True)
        
        # Save file
        file_path = os.path.join(unit_dir, unique_filename)
        file.save(file_path)
        
        # Get file size
        file_size = os.path.getsize(file_path)
        
        # Verify that the course and unit exist
        course = Course.query.get(course_id)
        if not course:
            os.remove(file_path)  # Clean up uploaded file
            return jsonify({'message': 'Course not found.'}), 404
            
        unit = Unit.query.get(unit_id)
        if not unit:
            os.remove(file_path)  # Clean up uploaded file
            return jsonify({'message': 'Unit not found.'}), 404
        
        # Verify unit belongs to the course
        if unit.course_id != course_id:
            os.remove(file_path)  # Clean up uploaded file
            return jsonify({'message': 'Unit does not belong to the specified course.'}), 400
        
        # Store file information in database
        note = Notes(
            lecturer_id=user_id,
            course_id=course_id,
            unit_id=unit_id,
            title=title,
            description=description,
            original_filename=original_filename,
            stored_filename=unique_filename,
            file_path=os.path.join('notes', f"course_{course_id}", f"unit_{unit_id}", unique_filename),
            file_size=file_size,
            file_type=file_extension,
            mime_type=ALLOWED_EXTENSIONS.get(file_extension)
        )
        
        db.session.add(note)
        db.session.commit()
        
        return jsonify({
            'message': 'Notes uploaded successfully.',
            'note_id': note.id,
            'file_info': {
                'title': title,
                'filename': original_filename,
                'file_type': file_extension,
                'file_size': file_size,
                'course_id': course_id,
                'unit_id': unit_id,
                'created_at': note.created_at.isoformat()
            }
        }), 201
        
    except Exception as e:
        # Clean up file if database operation fails
        if os.path.exists(file_path):
            os.remove(file_path)
        
        return jsonify({
            'message': 'Failed to upload notes.',
            'error': str(e)
        }), 500

# Route to delete a note (only by the lecturer who uploaded it)
@lec_blueprint.route('/notes/<note_id>', methods=['DELETE'])
def delete_note(note_id):
    user_id = get_jwt_identity()
    
    # Get note from database
    note = Notes.query.get(note_id)
    if not note:
        return jsonify({'message': 'Note not found.'}), 404
    
    # Check if the lecturer is the owner of the note
    if note.lecturer_id != user_id:
        return jsonify({'message': 'Access forbidden: You can only delete your own notes.'}), 403
    
    # Delete file from disk
    full_file_path = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), note.file_path)
    if os.path.exists(full_file_path):
        try:
            os.remove(full_file_path)
        except Exception as e:
            return jsonify({
                'message': 'Failed to delete file from disk.',
                'error': str(e)
            }), 500
    
    # Delete from database
    try:
        db.session.delete(note)
        db.session.commit()
        
        return jsonify({
            'message': 'Note deleted successfully.',
            'note_id': note_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'message': 'Failed to delete note from database.',
            'error': str(e)
        }), 500


# Route to get all notes uploaded by a specific lecturer
@lec_blueprint.route('/notes', methods=['GET'])
def get_lecturer_notes():
    user_id = get_jwt_identity()
    
    # Get all notes uploaded by this lecturer
    notes = Notes.query.filter_by(lecturer_id=user_id).order_by(Notes.created_at.desc()).all()
    
    return jsonify({
        'message': 'Lecturer notes retrieved successfully.',
        'notes': [note.to_dict() for note in notes]
    }), 200
