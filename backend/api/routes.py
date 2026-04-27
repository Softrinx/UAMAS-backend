"""
Blueprint for Students and Lecturers to access assessments, questions, and notes.
Created by: https://github.com/ByteBenders-compScientists/UAMAS-backend
Actions:
- Get all questions for a specific assessment
- Download a specific note file
- Get notes for a specific course and unit
"""
from flask import Blueprint, request, jsonify, current_app, send_from_directory
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from dotenv import load_dotenv

from api import db
from api.models import Assessment, Question, Submission, Answer, Result, TotalMarks, Course, Unit, Notes

import os

load_dotenv()
bd_blueprint = Blueprint('bd', __name__)

@bd_blueprint.route('/debug/upload-config', methods=['GET'])
def debug_upload_config():
    '''Debug endpoint to check upload configuration'''
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
    student_answers_dir = os.path.join(upload_folder, 'student_answers')
    
    # List files in the directory
    files = []
    if os.path.exists(student_answers_dir):
        files = os.listdir(student_answers_dir)[:10]  # First 10 files
    
    return jsonify({
        'upload_folder': upload_folder,
        'student_answers_dir': student_answers_dir,
        'absolute_path': os.path.abspath(student_answers_dir),
        'dir_exists': os.path.exists(student_answers_dir),
        'sample_files': files,
        'public_api_base_url': os.getenv('PUBLIC_API_BASE_URL', 'NOT SET'),
        'cwd': os.getcwd()
    }), 200

@bd_blueprint.route('/uploads/student_answers/<filename>', methods=['GET'])
def serve_student_answer_image(filename):
    '''
    Serve the uploaded student answer image.
    This endpoint allows serving the image files uploaded by students for their answers.
    The images are stored in the UPLOAD_FOLDER under 'student_answers'.
    '''
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
    student_answers_dir = os.path.join(upload_folder, 'student_answers')
    file_path = os.path.join(student_answers_dir, filename)
    
    # Log the request details for debugging
    current_app.logger.info(f"[SERVE_IMAGE] Request for image: {filename}")
    current_app.logger.info(f"[SERVE_IMAGE] Upload folder: {upload_folder}")
    current_app.logger.info(f"[SERVE_IMAGE] Full path: {file_path}")
    current_app.logger.info(f"[SERVE_IMAGE] File exists: {os.path.exists(file_path)}")
    
    if not os.path.exists(file_path):
        current_app.logger.error(f"[SERVE_IMAGE] File not found: {file_path}")
        return jsonify({'message': 'File not found.', 'path': file_path}), 404
    
    try:
        return send_from_directory(student_answers_dir, filename)
    except Exception as e:
        current_app.logger.error(f"[SERVE_IMAGE] Error serving file: {str(e)}")
        return jsonify({'message': 'Error serving file.', 'error': str(e)}), 500

# endpoint for students & lecturers to get questions of an assessment
@bd_blueprint.route('/assessments/<assessment_id>/questions', methods=['GET'])
@jwt_required(locations=['cookies', 'headers'])
def get_assessment_questions(assessment_id):
    """Get all questions for a specific assessment.
    This route allows both lecturers and students to view the questions of an assessment.
    Args:
        assessment_id (str): The ID of the assessment.
    Returns:
        JSON response containing the list of questions or an error message.
    """
    user_id = get_jwt_identity()
    claims = get_jwt()
    
    assessment = Assessment.query.get(assessment_id)
    if not assessment:
        return jsonify({'message': 'Assessment not found.'}), 404
    
    # Check if the user has access to the assessment: => Role: lecturer or student
    if claims['role'] != 'lecturer' and claims['role'] != 'student':
        return jsonify({'message': 'Access forbidden: Only lecturers or students can view assessment questions.'}), 403

    questions = Question.query.filter_by(assessment_id=assessment.id).all()
    return jsonify([question.to_dict() for question in questions]), 200

# Route to download a specific note file
@bd_blueprint.route('/notes/<note_id>/download', methods=['GET'])
@jwt_required(locations=['cookies', 'headers'])
def download_note(note_id):
    """Download a specific note file.
    This route allows both students and lecturers to download notes.
    Args:
        note_id (str): The ID of the note.
    Returns:
        JSON response containing the file or an error message.
    """
    user_id = get_jwt_identity()
    claims = get_jwt()
    
    # Both students and lecturers can download notes
    if claims.get('role') not in ['student', 'lecturer']:
        return jsonify({'message': 'Access forbidden.'}), 403
    
    from api.models import Notes
    from flask import send_file
    
    # Get note from database
    note = Notes.query.get(note_id)
    if not note:
        return jsonify({'message': 'Note not found.'}), 404
    
    # Construct full file path
    full_file_path = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), note.file_path)
    
    # Check if file exists
    if not os.path.exists(full_file_path):
        return jsonify({'message': 'File not found on disk.'}), 404
    
    try:
        return send_file(
            full_file_path,
            as_attachment=True,
            download_name=note.original_filename,
            mimetype=note.mime_type
        )
    except Exception as e:
        return jsonify({
            'message': 'Failed to download file.',
            'error': str(e)
        }), 500

# Additional route to get notes for a specific course and unit
@bd_blueprint.route('/units/<unit_id>/notes', methods=['GET'])
@jwt_required(locations=['cookies', 'headers'])
def get_notes(unit_id):
    """Get notes for a specific course and unit.
    This route allows both students and lecturers to view notes for a specific unit.
    Args:
        unit_id (str): The ID of the unit.
    Returns:
        JSON response containing the notes or an error message.
    """
    user_id = get_jwt_identity()
    claims = get_jwt()
    
    # Both students and lecturers can view notes
    if claims.get('role') not in ['student', 'lecturer']:
        return jsonify({'message': 'Access forbidden.'}), 403
    
    # Get course_id from the unit
    unit = Unit.query.get(unit_id)
    if not unit:
        return jsonify({'message': 'Unit not found.'}), 404
    course_id = unit.course_id
    
    # Verify course and unit exist
    course = Course.query.get(course_id)
    if not course:
        return jsonify({'message': 'Course not found.'}), 404
        
    unit = Unit.query.get(unit_id)
    if not unit:
        return jsonify({'message': 'Unit not found.'}), 404
    
    # Verify unit belongs to the course
    if unit.course_id != course_id:
        return jsonify({'message': 'Unit does not belong to the specified course.'}), 400
    
    # Query notes from database
    notes = Notes.query.filter_by(course_id=course_id, unit_id=unit_id).order_by(Notes.created_at.desc()).all()
    
    return jsonify({
        'message': 'Notes retrieved successfully.',
        'course': {
            'id': course.id,
            'name': course.name,
            'code': course.code
        },
        'unit': {
            'id': unit.id,
            'name': unit.unit_name,
            'code': unit.unit_code
        },
        'notes': [note.to_dict() for note in notes]
    }), 200

