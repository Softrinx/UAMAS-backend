"""
Blueprint for Student-Assessments API routes.
Created by: https://github.com/ByteBenders-compScientists/UAMAS-backend
Actions:
- Get all assessments for a student
- Get a specific assessment by ID
- Get all questions for a specific assessment
- Submit an answer for a specific question in an assessment
- Submit an assessment
- Get all submissions for a student (including completed and in-progress)
"""

from flask import Blueprint, request, jsonify, current_app, send_from_directory
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import logging

from api import db
# from api.models import Assessment, Question, Submission, Answer, Result, TotalMarks, Course, Unit, Notes, User, Lecturer, Student, AttemptAssessment
from api.models import Assessment, Question, Submission, Answer, Result, TotalMarks, Course, Unit, Notes, User, Lecturer, Student
from api.utils import grade_text_answer, grade_image_answer
from sqlalchemy.orm import joinedload

import os
import uuid
import random
# from datetime import datetime, timedelta
from flask import request, jsonify, current_app, url_for
from werkzeug.utils import secure_filename
import os, uuid, traceback
from PIL import Image

MAX_IMAGE_BYTES = 10 * 1024 * 1024

load_dotenv()
student_blueprint = Blueprint('student', __name__)

@student_blueprint.before_request
@jwt_required(locations=['cookies', 'headers'])
def verify_jwt():
    """
    Verify the JWT token and ensure the user is a student.
    """
    user_id = get_jwt_identity()
    claims = get_jwt()
    if claims['role'] != 'student':
        return jsonify({"msg": "Access forbidden: Students only"}), 403
    
@student_blueprint.route('/assessments', methods=['GET'])
def get_student_assessments():
    """
    Get all assessments for the courses the student is enrolled in.
    """
    user_id = get_jwt_identity()

    # load student
    student = Student.query.options(joinedload(Student.units)).filter_by(user_id=user_id).first()
    if not student:
        return jsonify({'message': 'Student not found.'}), 404
    
    # Batch fetch assessments for all units at once (instead of looping per unit)
    unit_ids = [unit.id for unit in student.units]
    if not unit_ids:
        return jsonify({'message': 'No assessments found.'}), 404
    
    assessments = Assessment.query.filter(
        Assessment.unit_id.in_(unit_ids),
        Assessment.verified == True
    ).all()

    if not assessments:
        return jsonify({'message': 'No assessments found.'}), 404

    assessment_ids = [a.id for a in assessments]
    
    # Batch fetch all submissions for this student (single query instead of per-assessment)
    submissions = Submission.query.filter(
        Submission.assessment_id.in_(assessment_ids),
        Submission.student_id == user_id
    ).all()
    submission_map = {s.assessment_id: s for s in submissions}
    
    # Batch fetch all answers upfront (single query)
    all_answers = Answer.query.filter_by(student_id=user_id).all()
    answered_question_ids = {answer.question_id for answer in all_answers}
    answer_assessment_map = {answer.assessment_id for answer in all_answers}

    # build the payload
    payload = []
    for a in assessments:
        # Check submission from pre-fetched map (no query)
        submission = submission_map.get(a.id)

        if submission:
            status = 'completed'
        else:
            # Check if any answered questions exist in this assessment (no query)
            status = 'in-progress' if a.id in answer_assessment_map else 'start'

        payload.append({
            'id': a.id,
            'topic': a.topic,
            'creator_id': a.creator_id,
            'week': a.week,
            'title': a.title,
            'description': a.description,
            'questions_type': a.question_types,
            'type': a.type,
            'unit_id': a.unit_id,
            'course_id': a.course_id,
            'total_marks': a.total_marks,
            'number_of_questions': a.number_of_questions,
            'difficulty': a.difficulty,
            'verified': a.verified,
            'created_at': a.created_at.isoformat(),
            'level': a.level,
            'semester': a.semester,
            'schedule_date': a.schedule_date.isoformat() if a.schedule_date else None,
            'deadline': a.deadline.isoformat() if a.deadline else None,
            'duration': a.duration,
            'blooms_level': a.blooms_level,
            'questions': [q.to_dict() for q in a.questions] if a.questions else [],
            'status': status
        })

        # shuffle the questions for each assessment
        random.shuffle(payload[-1]['questions'])

    # tag each question with answered/not answered
    for asses in payload:
        for q in asses['questions']:
            q['status'] = 'answered' if q['id'] in answered_question_ids else 'not answered'
    
    # print(payload[0].get('schedule_date'))
    # print(payload[1].get('schedule_date'))

    return jsonify(payload), 200

@student_blueprint.route('/questions/<question_id>/answer', methods=['POST'])
def submit_answer(question_id):
    """
    Submit an answer for a specific question in an assessment.
    """
    user_id = get_jwt_identity()
    logger = logging.getLogger(__name__)
    logger.info(f"[SUBMIT_ANSWER] Starting - Student: {user_id}, Question: {question_id}")

    question = Question.query.get(question_id)
    print(question, question_id)
    if not question:
        logger.warning(f"[SUBMIT_ANSWER] Question not found: {question_id}")
        return jsonify({'message': 'Question not found.'}), 404

    assessment = Assessment.query.get(question.assessment_id)
    if not assessment:
        logger.warning(f"[SUBMIT_ANSWER] Assessment not found: {question.assessment_id}")
        return jsonify({'message': 'Assessment not found.'}), 404

    # Prevent duplicate submissions
    existing_answer = Answer.query.filter_by(question_id=question.id, student_id=user_id).first()
    if existing_answer:
        return jsonify({'message': 'You have already submitted an answer for this question.'}), 400

    # Accept either form-data or JSON
    if request.content_type and request.content_type.startswith('application/json'):
        data = request.get_json() or {}
    else:
        data = request.form

    answer_type = data.get('answer_type')
    if answer_type not in ['text', 'image']:
        return jsonify({'message': 'Invalid answer type. Must be "text" or "image".'}), 400

    text_answer = None
    image_filename = None
    full_file_path = None
    image_public_url = None

    try:
        if answer_type == 'image':
            logger.info(f"[SUBMIT_ANSWER] Image response detected - Student: {user_id}, Question: {question_id}")
            if 'image' not in request.files:
                logger.warning(f"[SUBMIT_ANSWER] No image file in request - Student: {user_id}")
                return jsonify({'message': 'Image file is required for image answers.'}), 400

            image_file = request.files['image']
            original_filename = image_file.filename or ''
            if original_filename == '':
                logger.warning(f"[SUBMIT_ANSWER] Empty filename - Student: {user_id}")
                return jsonify({'message': 'Uploaded file must have a filename.'}), 400

            # extension check
            _, ext = os.path.splitext(original_filename)
            ext = ext.lower().lstrip('.')
            allowed = set(current_app.config.get('ALLOWED_EXTENSIONS', {'png','jpg','jpeg'}))
            if ext not in allowed:
                logger.warning(f"[SUBMIT_ANSWER] Invalid extension '{ext}' - Student: {user_id}")
                allowed_list = ", ".join(sorted(allowed))
                return jsonify({'message': f"Invalid image type. Allowed: {allowed_list}"}), 400

            logger.info(f"[SUBMIT_ANSWER] File extension valid: {ext} - Student: {user_id}")

            # size check - some WSGI servers provide content_length; if not, we read bytes
            image_file.stream.seek(0, os.SEEK_END)
            size = image_file.stream.tell()
            image_file.stream.seek(0)
            if size > MAX_IMAGE_BYTES:
                logger.warning(f"[SUBMIT_ANSWER] Image too large ({size} bytes) - Student: {user_id}")
                return jsonify({'message': f'Image too large. Max {MAX_IMAGE_BYTES} bytes.'}), 400

            logger.info(f"[SUBMIT_ANSWER] Image size valid: {size} bytes - Student: {user_id}")
            
            # secure filename and save
            filename = f"{uuid.uuid4().hex}_{secure_filename(original_filename)}"
            upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'student_answers')
            os.makedirs(upload_dir, exist_ok=True)
            full_file_path = os.path.join(upload_dir, filename)
            image_file.save(full_file_path)
            image_filename = filename
            logger.info(f"[SUBMIT_ANSWER] Image saved - Filename: {filename}, Path: {full_file_path}, Student: {user_id}")

            # Verify image is valid (Pillow)
            try:
                with Image.open(full_file_path) as img:
                    img.verify()  # will raise if not an image
                logger.info(f"[SUBMIT_ANSWER] Image validation passed - Student: {user_id}, Filename: {filename}")
            except Exception as e:
                # remove bad file
                logger.error(f"[SUBMIT_ANSWER] Image validation failed - Error: {str(e)}, Student: {user_id}, Filename: {filename}")
                try:
                    os.remove(full_file_path)
                except Exception:
                    pass
                return jsonify({'message': 'Uploaded file is not a valid image.'}), 400

        else:
            # text answer path
            logger.info(f"[SUBMIT_ANSWER] Text response detected - Student: {user_id}, Question: {question_id}")
            text_answer = data.get('text_answer', '')
            if not text_answer:
                logger.warning(f"[SUBMIT_ANSWER] Empty text answer - Student: {user_id}")
                return jsonify({'message': 'Text answer is required for text submissions.'}), 400

        # Save the raw answer
        answer = Answer(
            question_id=question.id,
            assessment_id=assessment.id,
            student_id=user_id,
            text_answer=text_answer,
            image_path=image_filename,
        )
        db.session.add(answer)
        db.session.commit()
        logger.info(f"[SUBMIT_ANSWER] Answer saved to DB - Answer ID: {answer.id}, Student: {user_id}, Question: {question_id}, Image: {image_filename}")

        # Fetch student hobbies
        student = Student.query.filter_by(user_id=user_id).first()
        student_hobbies = student.hobbies if student and student.hobbies else []

        # Call grading function
        if text_answer:
            logger.info(f"[SUBMIT_ANSWER] Grading text answer - Student: {user_id}, Question: {question_id}")
            grading_result, status = grade_text_answer(
                text_answer=text_answer,
                question_text=question.text,
                rubric=question.rubric,
                correct_answer=question.correct_answer,
                marks=question.marks,
                student_hobbies=student_hobbies
            )
        else:
            # Pass the full file path so grader can open it
            logger.info(f"[SUBMIT_ANSWER] Grading image answer - Student: {user_id}, Question: {question_id}, File: {full_file_path}")
            grading_result, status = grade_image_answer(
                filename=full_file_path,
                question_text=question.text,
                rubric=question.rubric,
                correct_answer=question.correct_answer,
                marks=question.marks,
                student_hobbies=student_hobbies
            )
            logger.info(f"[SUBMIT_ANSWER] Image grading result - Status: {status}, Score: {grading_result.get('score')}, Student: {user_id}")

        if status != 200:
            # grader returned an error — keep the raw answer but surface the grader error
            logger.error(f"[SUBMIT_ANSWER] Grading failed - Status: {status}, Student: {user_id}, Question: {question_id}, Error: {grading_result}")
            return jsonify(grading_result), status

        # persist result
        logger.info(f"[SUBMIT_ANSWER] Saving result to DB - Score: {grading_result['score']}, Student: {user_id}, Question: {question_id}")
        result = Result(
            question_id=question.id,
            assessment_id=assessment.id,
            student_id=user_id,
            score=grading_result['score'],
            feedback=grading_result.get('feedback', '')
        )
        db.session.add(result)
        db.session.commit()
        logger.info(f"[SUBMIT_ANSWER] Result saved - Result ID: {result.id}, Student: {user_id}")

        return jsonify({
            'message': 'Answer submitted successfully.',
            'question_id': question.id,
            'assessment_id': assessment.id,
            'score': grading_result['score'],
            'feedback': grading_result.get('feedback', '')
        }), 201

    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"[SUBMIT_ANSWER] Exception occurred - Student: {user_id}, Question: {question_id}, Error: {str(e)}, Traceback: {traceback.format_exc()}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'message': 'Internal server error.'}), 500

@student_blueprint.route('/assessments/<assessment_id>/submit', methods=['GET'])
def submit_assessment(assessment_id):
    """
    Submit an assessment.
    This endpoint allows a student to submit an assessment after answering all questions.
    It checks if the student has already submitted the assessment and calculates total marks.
    Only students can access this endpoint.
    The submission is considered graded by default.
    """
    user_id = get_jwt_identity()

    assessment = Assessment.query.get(assessment_id)
    if not assessment:
        return jsonify({'message': 'Assessment not found.'}), 404

    # Check if the student has already submitted this assessment
    existing_submission = Submission.query.filter_by(assessment_id=assessment.id, student_id=user_id).first()
    if existing_submission:
        return jsonify({'message': 'You have already submitted this assessment.'}), 400

    # Create a new submission
    submission = Submission(
        assessment_id=assessment.id,
        student_id=user_id,
        graded=True,  # Assume submission is graded by default
    )
    
    db.session.add(submission)
    db.session.commit()

    # Calculate total marks in Python
    results = Result.query.filter_by(
        student_id=user_id,
        assessment_id=assessment.id
    ).all()

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

    total_marks_entry = TotalMarks(
        student_id=user_id,
        assessment_id=assessment.id,
        submission_id=submission.id,
        total_marks=total_marks
    )
    
    db.session.add(total_marks_entry)
    db.session.commit()

    return jsonify({
        'message': 'Assessment submitted successfully.',
        'submission_id': submission.id,
        'total_marks': total_marks
    }), 201

@student_blueprint.route('/submissions', methods=['GET'])
def get_student_submissions():
    """
    Get all submissions for a student.
    This endpoint returns all submissions made by the student, including completed and in-progress ones.
    """
    user_id = get_jwt_identity()
    logger = logging.getLogger(__name__)
    logger.info(f"[GET_SUBMISSIONS] Fetching submissions - Student: {user_id}")

    submissions = Submission.query.filter_by(student_id=user_id).all()
    if not submissions:
        logger.warning(f"[GET_SUBMISSIONS] No submissions found - Student: {user_id}")
        return jsonify({'message': 'No submissions found for this student.'}), 404

    submission_ids = [s.id for s in submissions]
    assessment_ids = [s.assessment_id for s in submissions]
    
    # Batch fetch total marks (single query instead of per-submission)
    total_marks_list = TotalMarks.query.filter(TotalMarks.submission_id.in_(submission_ids)).all()
    total_marks_map = {tm.submission_id: tm for tm in total_marks_list}
    
    # Batch fetch all results (single query instead of per-submission)
    results_list = Result.query.options(joinedload(Result.answer)).filter(
        Result.assessment_id.in_(assessment_ids),
        Result.student_id == user_id
    ).all()
    results_by_assessment = {}
    for result in results_list:
        if result.assessment_id not in results_by_assessment:
            results_by_assessment[result.assessment_id] = []
        results_by_assessment[result.assessment_id].append(result)
    
    # Batch fetch all questions (single query instead of per-result)
    all_question_ids = [r.question_id for r in results_list]
    questions = Question.query.filter(Question.id.in_(all_question_ids)).all() if all_question_ids else []
    question_map = {q.id: q for q in questions}
    
    # Batch fetch all assessments (single query instead of per-submission)
    assessments = Assessment.query.filter(Assessment.id.in_(assessment_ids)).all()
    assessment_map = {a.id: a for a in assessments}

    logger.info(f"[GET_SUBMISSIONS] Found {len(submissions)} submissions - Student: {user_id}")

    # combined the submissions with their total marks and results
    submissions_data = []
    for submission in submissions:
        total_marks_entry = total_marks_map.get(submission.id)
        results = results_by_assessment.get(submission.assessment_id, [])

        logger.info(f"[GET_SUBMISSIONS] Processing submission - Submission ID: {submission.id}, Student: {user_id}")

        results_data = []
        for result in results:
            logger.debug(f"[GET_SUBMISSIONS] Processing result - Result ID: {result.id}, Has Answer: {result.answer is not None}, Has Image: {result.answer.image_path if result.answer else None}")
            result_dict = result.to_dict()
            # Get the question from pre-fetched map (no query)
            question = question_map.get(result.question_id)
            result_dict['question_text'] = question.text if question else None
            result_dict['marks'] = question.marks if question else None
            result_dict['rubric'] = question.rubric if question else None
            result_dict['correct_answer'] = question.correct_answer if question else None
            results_data.append(result_dict)

        # Get assessment from pre-fetched map (no query)
        assessment = assessment_map.get(submission.assessment_id)
        
        if assessment:
            submission_data = {
                'assessment_id': assessment.id,
                'unit_id': assessment.unit_id,
                'topic': assessment.topic,
                'number_of_questions': assessment.number_of_questions,
                'difficulty': assessment.difficulty,
                'deadline': assessment.deadline.isoformat() if assessment.deadline else None,
                'duration': assessment.duration,
                'blooms_level': assessment.blooms_level,
                'created_at': assessment.created_at.isoformat(),
            }
        else:
            submission_data = {
                'assessment_id': submission.assessment_id,
                'unit_id': None,
                'topic': None,
                'number_of_questions': None,
                'difficulty': None,
                'deadline': None,
                'duration': None,
                'blooms_level': None,
                'created_at': None,
            }

        submission_data.update({
            'submission_id': submission.id,
            'graded': submission.graded,
            'total_marks': total_marks_entry.total_marks if total_marks_entry else 0,
            'results': results_data,
        })
        submissions_data.append(submission_data)

    return jsonify(submissions_data), 200

@student_blueprint.route('/notes', methods=['GET'])
def get_student_notes():
    """
    Get all notes for the courses a student is enrolled in.
    """
    user_id = get_jwt_identity()

    student = Student.query.options(joinedload(Student.units)).filter_by(user_id=user_id).first()
    if not student:
        return jsonify({'message': 'Student not found.'}), 404

    unit_ids = [unit.id for unit in student.units]
    if not unit_ids:
        return jsonify({'message': 'Student is not enrolled in any unit.'}), 404

    notes = (
        Notes.query
             .filter(Notes.unit_id.in_(unit_ids))
             .all()
    )
    if not notes:
        return jsonify({'message': 'No notes found for your units.'}), 404

    # course_map = {c.id: c.name for c in student.courses}
    unit_ids   = {n.unit_id for n in notes if n.unit_id}
    units      = Unit.query.filter(Unit.id.in_(unit_ids)).all()
    unit_map   = {u.id: u.unit_name for u in units}

    notes_data = []
    for note in notes:
        nd = note.to_dict()
        # nd['course_name'] = course_map.get(note.course_id)
        nd['unit_name']   = unit_map.get(note.unit_id)
        notes_data.append(nd)

    return jsonify(notes_data), 200


# # handle timing(duration) for the assessment at the frontend
# @student_blueprint.route('/start_assessment/<assessment_id>', methods=['POST'])
# def start_assessment(assessment_id):
#     """
#     Record the start of an assessment attempt for a student.
#     This endpoint creates an AttemptAssessment entry to track when the student started the assessment.
#     """
#     user_id = get_jwt_identity()

#     assessment = Assessment.query.get(assessment_id)
#     if not assessment:
#         return jsonify({'message': 'Assessment not found.'}), 404

#     # Check if the student has already started this assessment
#     existing_attempt = AttemptAssessment.query.filter_by(assessment_id=assessment.id, student_id=user_id).first()
#     if existing_attempt:
#         # return jsonify({'message': 'You have already started this assessment.'}), 400

#         # fetch time attempt details
#         return jsonify({
#             'message': 'Assessment attempt started successfully.',
#             'attempt_id': existing_attempt.id,
#             'start_time': existing_attempt.started_at.isoformat()
#         }), 201

#     # Create a new attempt record
#     attempt = AttemptAssessment(
#         assessment_id=assessment.id,
#         student_id=user_id,
#         duration=assessment.duration  # in minutes
#     )
    
#     db.session.add(attempt)
#     db.session.commit()

#     return jsonify({
#         'message': 'Assessment attempt started successfully.',
#         'attempt_id': attempt.id,
#         'start_time': attempt.started_at.isoformat()
#     }), 201

# @student_blueprint.route('/time_remaining/<assessment_id>', methods=['GET'])
# def get_time_remaining(assessment_id):
#     """
#     Get the remaining time for an ongoing assessment attempt.
#     """
#     user_id = get_jwt_identity()

#     attempt = AttemptAssessment.query.filter_by(assessment_id=assessment_id, student_id=user_id).first()
#     if not attempt:
#         return jsonify({'message': 'No ongoing assessment found.'}), 404

#     # Calculate the time remaining
#     time_elapsed = (datetime.utcnow() - attempt.started_at).total_seconds() / 60  # in minutes
#     time_remaining = attempt.duration - time_elapsed

#     # auto-submit if time is up and not yet submitted
#     if time_remaining <= 0 and not attempt.submitted:
#         # mark as submitted
#         submission = Submission(
#             assessment_id=assessment_id,
#             student_id=user_id,
#             graded=True
#         )
#         db.session.add(submission)
#         db.session.commit()
#         attempt.submitted = True
#         db.session.commit()
#         return jsonify({'message': 'Time is up. Assessment has been auto-submitted.'}), 200

#     return jsonify({
#         'assessment_id': assessment_id,
#         'time_remaining': max(0, time_remaining)
#     }), 200
