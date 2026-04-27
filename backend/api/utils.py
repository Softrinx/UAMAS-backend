"""
Contain Utility functions for the UAMAS backend
Created by: https://github.com/ByteBenders-compScientists/UAMAS-backend
Actions:
- Create a comprehensive assessment based on user input
- Grade image answers using AI
- Grade text answers using AI
"""

from dotenv import load_dotenv
from openai import OpenAI
import os
import json
import re
import logging

import base64
import mimetypes
import io
from pypdf import PdfReader

load_dotenv()

# Set up logging
logger = logging.getLogger(__name__)

# Allowed question type values expected from the UI
ALLOWED_QUESTION_TYPES = [
    "open-ended",
    "close-ended-multiple-single",
    "close-ended-multiple-multiple",
    "close-ended-bool",
    "close-ended-matching",
    "close-ended-ordering",
    "close-ended-drag-drop",
]

# OpenAI client setup
openai_api_key = os.getenv('OPENAI_API_KEY')
model_deployment_name = os.getenv('GPT_MODEL')
openai_endpoint = os.getenv('GPT_ENDPOINT')
model_deployment_name_image = os.getenv('GPT_IMAGE_MODEL')

logger.info(f"[UTILS] Initializing OpenAI client - Endpoint: {openai_endpoint}, Text Model: {model_deployment_name}, Image Model: {model_deployment_name_image}")
if not openai_api_key:
    logger.warning("[UTILS] OPENAI_API_KEY not set!")
if not openai_endpoint:
    logger.warning("[UTILS] GPT_ENDPOINT not set!")
if not model_deployment_name:
    logger.warning("[UTILS] GPT_MODEL not set!")

client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_endpoint,
    timeout=120 # hard network timeout
    # max_tries=2
)
logger.info(f"[UTILS] OpenAI client initialized successfully")


def _normalize_question_types(raw_types):
    """Return a cleaned list constrained to ALLOWED_QUESTION_TYPES."""
    qtypes = raw_types if isinstance(raw_types, (list, tuple)) else [raw_types]
    cleaned = []
    for qt in qtypes:
        if qt is None:
            continue
        s = str(qt).strip()
        if s and s in ALLOWED_QUESTION_TYPES:
            cleaned.append(s)
    return cleaned or ["open-ended"]


def _get_blooms_level_guidance(blooms_level):
    """
    Map Bloom's taxonomy levels to specific question design requirements.
    Returns guidance text that emphasizes higher-order thinking.
    """
    blooms_mapping = {
        "Remember": (
            "Even for recall, embed questions in realistic scenarios requiring application. "
            "Students must demonstrate they understand WHEN and WHY to use this knowledge, not just WHAT it is."
        ),
        "Understand": (
            "Require explanation in the student's own words with concrete examples from novel contexts. "
            "Ask students to rephrase concepts, provide analogies, or explain to a peer."
        ),
        "Apply": (
            "Use novel scenarios NOT covered in course materials. Present new situations where students "
            "must apply learned concepts. Include code snippets, case studies, or real-world problems."
        ),
        "Analyze": (
            "Require breaking down complex concepts, identifying relationships, comparing approaches, "
            "finding patterns, or diagnosing problems. Include 'what's wrong with this code/approach' questions."
        ),
        "Evaluate": (
            "Ask for justified judgments, critical assessment of solutions, comparison of alternatives with "
            "trade-off analysis, or critique of given approaches with evidence-based reasoning."
        ),
        "Create": (
            "Require synthesis of multiple concepts into new solutions. Design questions asking students to "
            "build, propose, design, or formulate novel approaches to problems."
        )
    }
    
    return blooms_mapping.get(blooms_level, blooms_mapping["Apply"])


def _get_type_specific_instructions(question_types):
    """
    Generate detailed instructions for each question type to ensure 
    questions require deep thinking and cannot be easily answered by AI.
    """
    instructions = []
    
    if 'open-ended' in question_types:
        instructions.append(
            "FOR OPEN-ENDED QUESTIONS:\n"
            "- Structure as multi-part questions (a) analyze/identify, (b) explain why, (c) propose solution\n"
            "- Include code snippets to debug, improve, or extend\n"
            "- Require 'explain your reasoning' or 'justify your answer' for every claim\n"
            "- Use realistic scenarios from industry or research contexts\n"
            "- Ask students to compare multiple approaches and recommend the best with justification\n"
            "- Include 'what would happen if we changed X to Y' predictive questions\n"
            "- Award marks: 30-40% for correct answer, 60-70% for explanation and reasoning"
        )
    
    if any('close-ended-multiple' in qt for qt in question_types):
        instructions.append(
            "FOR MULTIPLE-CHOICE QUESTIONS:\n"
            "- ALL distractors must be plausible to someone with partial understanding\n"
            "- Base incorrect options on common student misconceptions or errors\n"
            "- Include scenario-based stems with code snippets or case descriptions\n"
            "- Use formats like: 'Which approach is MOST appropriate when...' or 'What is the PRIMARY reason...'\n"
            "- Create options requiring careful analysis (avoid obviously wrong answers)\n"
            "- For multiple-answer questions, ensure partial credit is possible but challenging\n"
            "- Shuffle answer order to avoid patterns like 'C is often correct'"
        )
    
    if 'close-ended-bool' in question_types:
        instructions.append(
            "FOR TRUE/FALSE QUESTIONS:\n"
            "- ALWAYS require written justification: 'State True or False AND explain why'\n"
            "- Award points: 20% for correct T/F, 80% for explanation\n"
            "- Use nuanced statements requiring careful analysis of edge cases\n"
            "- Include context: 'In the context of [scenario], statement X is True/False'\n"
            "- Avoid absolute statements (always/never) unless testing specific edge cases\n"
            "- Create statements that seem correct at first glance but have subtle issues"
        )
    
    if 'close-ended-matching' in question_types:
        instructions.append(
            "FOR MATCHING QUESTIONS:\n"
            "- Match concepts to scenarios/applications rather than definitions\n"
            "- Include more items in one column than the other to increase difficulty\n"
            "- Use code examples, output results, or error messages as matching elements\n"
            "- Require understanding of when/why to apply each concept, not just recognition"
        )
    
    if 'close-ended-ordering' in question_types:
        instructions.append(
            "FOR ORDERING QUESTIONS:\n"
            "- Order steps in algorithms, debugging processes, or development workflows\n"
            "- Include steps that could plausibly go in different orders for partial solutions\n"
            "- Require understanding of dependencies and logical flow\n"
            "- Use real-world scenarios: 'Order these steps to debug a memory leak'"
        )
    
    if 'close-ended-drag-drop' in question_types:
        instructions.append(
            "FOR DRAG-AND-DROP QUESTIONS:\n"
            "- Map code components to their purposes or outputs\n"
            "- Classify examples into categories based on characteristics\n"
            "- Match error messages to their root causes\n"
            "- Ensure understanding of categorization principles, not memorization"
        )
    
    return "\n\n".join(instructions) if instructions else ""


def ai_create_assessment(data):
    '''
    Create a comprehensive assessment using AI based on the provided parameters.
    This function constructs enhanced prompts that generate questions requiring
    deep understanding, critical thinking, and application rather than simple recall.
    '''
    
    # Enhanced system prompt focusing on higher-order thinking
    system_prompt = (
        "You are an expert instructional designer and university lecturer specializing in creating "
        "assessments that test deep understanding and application rather than memorization or recall. "
        
        "CRITICAL REQUIREMENTS - READ CAREFULLY:\n"
        "1. Design questions requiring synthesis, analysis, and application of concepts in NEW contexts\n"
        "2. AVOID questions answerable by direct copy-paste from textbooks, lecture notes, or AI chatbots\n"
        "3. Include scenario-based questions requiring contextualized problem-solving\n"
        "4. For multiple-choice: create plausible distractors reflecting common misconceptions\n"
        "5. Require students to justify reasoning, compare approaches, identify errors, or explain trade-offs\n"
        "6. Emphasize 'WHY' and 'HOW' over 'WHAT' - demand explanation of thought processes\n"
        "7. Award substantial marks for reasoning and methodology, not just final answers\n"
        
        "QUESTION DESIGN PATTERNS TO PRIORITIZE:\n"
        "- Real-world case studies requiring analysis and actionable recommendations\n"
        "- Code debugging scenarios with explanation of the bug's cause and fix\n"
        "- Comparative analysis (compare X vs Y in context Z, with justification)\n"
        "- Application to scenarios NOT directly covered in typical course materials\n"
        "- Hypothetical scenarios: 'What would happen if we modified X to Y? Explain.'\n"
        "- Multi-step problems requiring sequential reasoning and intermediate explanations\n"
        "- Error identification: 'A student claims [incorrect statement]. Identify and correct the error.'\n"
        "- Trade-off analysis: 'Which approach is best for scenario X? Justify with pros/cons.'\n"
        
        "ANTI-PATTERNS TO AVOID:\n"
        "- Simple definition questions ('What is inheritance?')\n"
        "- Direct recall from lecture slides or textbooks\n"
        "- Questions answerable by searching the exact phrase\n"
        "- True/false without required explanation\n"
        "- Multiple choice with obviously wrong distractors\n"
        
        "Follow Bloom's taxonomy rigorously - prioritize Analysis, Evaluation, and Creation levels over Remember/Understand. "
        "Produce detailed marking rubrics that explicitly reward reasoning, justification, and methodology (minimum 50% of marks). "
        "Strictly follow the JSON schema provided. "
        "For multiple choices, shuffle options and ensure distractors test understanding of WHY wrong answers are incorrect."
    )

    # Get question types and generate type-specific instructions
    question_types = _normalize_question_types(data.get('questions_type', []))
    question_type_label = ", ".join(question_types) if len(question_types) > 1 else question_types[0]
    type_specific_instructions = _get_type_specific_instructions(question_types)
    
    # Get Bloom's level-specific guidance
    blooms_level = data.get('blooms_level', 'Apply')
    blooms_guidance = _get_blooms_level_guidance(blooms_level)

    # Enhanced user prompt with detailed requirements
    user_prompt = (
        f"Create a {data['difficulty']} level assessment for the unit '{data['unit_name']}' "
        f"on the topic '{data['topic']}'. "
        f"Context/Description: {data['description']}\n\n"
        
        f"BLOOM'S TAXONOMY LEVEL: '{blooms_level}'\n"
        f"Specific Requirement: {blooms_guidance}\n\n"
        
        f"Generate {data['number_of_questions']} questions using types: {question_type_label}, "
        f"totaling {data['total_marks']} marks.\n\n"
        
        "MANDATORY REQUIREMENTS FOR EVERY QUESTION:\n"
        "1. Questions MUST require understanding of underlying principles, NOT memorization\n"
        "2. Include realistic scenarios, code examples, or case studies that students must analyze\n"
        "3. For MCQs: ALL distractors must represent common misconceptions or partial understanding\n"
        "4. For open-ended: structure as multi-part (identify + explain + apply/justify)\n"
        "5. Questions should NOT be answerable by:\n"
        "   - Simple Google search of the question text\n"
        "   - Direct prompting of AI like ChatGPT without understanding\n"
        "   - Copy-pasting from lecture slides or textbook definitions\n"
        "6. ALWAYS include components requiring explanation: 'explain why', 'justify your answer', "
        "'compare and contrast', 'what would happen if', 'identify the error and explain'\n"
        "7. Design rubrics awarding: 30-40% for final answer, 60-70% for reasoning/methodology\n\n"
        
        f"{type_specific_instructions}\n\n"
        
        "QUESTION TYPES TO EMPHASIZE:\n"
        "- Debugging: Provide code with bugs, ask students to find and explain the issue\n"
        "- Error Analysis: 'A student claims [wrong statement]. What's the error? Explain the correct concept.'\n"
        "- Comparison: 'When would you use approach X vs Y? Justify with scenarios.'\n"
        "- Prediction: 'If we modify this code from X to Y, what happens? Why?'\n"
        "- Best Practices: 'Which implementation is better for [context]? Explain trade-offs.'\n"
        "- Scenario Application: Present a new scenario and ask how concepts apply\n\n"
        
        "OUTPUT FORMAT:\n"
        "Structure output strictly as a JSON array of question objects with this EXACT shape:\n"
        """[
            {
                "text": "Question with scenario/context requiring analysis and application",
                "marks": <integer>,
                "type": "<question_type>",
                "blooms_level": "<cognitive_level>",
                "rubric": "Detailed rubric with breakdown: e.g., '2 marks: correct identification, 3 marks: explanation of reasoning, 2 marks: justification with examples. Partial credit: 1 mark if approach is partially correct but reasoning incomplete.'",
                "correct_answer": ["Comprehensive model answer including reasoning, not just the final answer"],
                "choices": null OR array_based_on_type
            }
        ]
        
        RULES FOR CHOICES BY TYPE:
        - open-ended: choices = null
        - close-ended-bool: choices = ["True", "False"]
        - close-ended-multiple-single: choices = array of options; correct_answer = array with ONE option
        - close-ended-multiple-multiple: choices = array of options; correct_answer = array with 1+ correct options
        - close-ended-ordering: choices = array to be ordered; correct_answer = correctly ordered array
        - close-ended-matching: choices = [["source0", "source1", ...], ["target0", "target1", ...]]
        - close-ended-drag-drop: choices = [["draggable0", "draggable1", ...], ["target0", "target1", ...]]
        """
        
        f"Every question's type MUST be exactly one of: {', '.join(ALLOWED_QUESTION_TYPES)}.\n"
        "Respond ONLY with the JSON array - NO additional commentary, explanation, or markdown formatting."
    )

    # Call the LLM with increased token limit and adjusted temperature

    content = ""

    try:
        stream = client.chat.completions.create(
            model=model_deployment_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=9000,      # REDUCED
            temperature=0.8,
            top_p=0.95,
            stream=True
        )

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content += chunk.choices[0].delta.content

    except Exception as e:
        # Log the error and raise a more informative exception
        error_message = f"Error during AI assessment generation: {type(e).__name__}: {str(e)}"
        logger.error(error_message, exc_info=True)
        raise RuntimeError(error_message) from e

    if not content:
        error_message = "AI model returned empty content"
        logger.error(error_message)
        raise RuntimeError(error_message)

    return content
    # res = client.chat.completions.create(
    #     model=model_deployment_name,
    #     messages=[
    #         {"role": "system", "content": system_prompt},
    #         {"role": "user", "content": user_prompt}
    #     ],
    #     max_tokens=15000,  # Increased for more detailed questions
    #     temperature=0.8,   # Slightly higher for more creative, varied questions
    #     top_p=0.95,
    #     stream=False
    # )

    # return res


def ai_create_assessment_from_pdf(data, pdf_path):
    '''
    Create an AI-generated assessment based on the content of a PDF document.
    Questions are designed to test deep understanding and application of the material,
    not simple recall of facts from the document.
    '''
    # Read and extract text from the PDF file
    with open(pdf_path, 'rb') as pdf_file:
        reader = PdfReader(pdf_file)
        text = []
        for page in reader.pages:
            text.append(page.extract_text() or "")
    document_text = "\n".join(text)

    # Enhanced system prompt
    system_prompt = (
        "You are an expert instructional designer and university lecturer specializing in creating "
        "assessments that test deep understanding and application rather than recall. "
        
        "You have been provided with course material in PDF format. Your task is to create questions "
        "that test whether students truly UNDERSTAND and can APPLY the concepts, not whether they can "
        "memorize and regurgitate text from the document.\n"
        
        "CRITICAL REQUIREMENTS:\n"
        "1. Design questions requiring synthesis, analysis, and application of concepts from the document\n"
        "2. NEVER ask questions that can be answered by copy-pasting directly from the PDF\n"
        "3. Create scenario-based questions that apply document concepts to NEW situations\n"
        "4. For multiple-choice: distractors must reflect common misconceptions about the material\n"
        "5. Require justification, comparison, error identification, or explanation of reasoning\n"
        "6. Emphasize 'WHY' and 'HOW' questions that test understanding of principles\n"
        "7. Questions should require students to have READ and UNDERSTOOD the material, not just searched it\n"
        
        "QUESTION DESIGN PATTERNS:\n"
        "- Apply document concepts to scenarios NOT mentioned in the PDF\n"
        "- Compare/contrast concepts from different sections of the document\n"
        "- Identify errors in example code/approaches that misuse document concepts\n"
        "- Predict outcomes when document principles are applied to new contexts\n"
        "- Evaluate which approach from the document fits a given novel scenario\n"
        "- Synthesize multiple concepts from the document to solve complex problems\n"
        
        "Follow Bloom's taxonomy rigorously - prioritize Analysis, Synthesis, and Evaluation. "
        "Produce detailed marking rubrics rewarding reasoning (60-70% of marks) over final answers. "
        "Strictly follow the JSON schema. "
        "For multiple choices, shuffle options and ensure distractors test conceptual understanding."
    )

    question_types = _normalize_question_types(data.get('questions_type', []))
    question_type_label = ", ".join(question_types) if len(question_types) > 1 else question_types[0]
    type_specific_instructions = _get_type_specific_instructions(question_types)
    blooms_level = data.get('blooms_level', 'Apply')
    blooms_guidance = _get_blooms_level_guidance(blooms_level)

    user_prompt = (
        f"Using the following document content, generate a {data['difficulty']} level assessment "
        f"for the unit '{data['unit_name']}' on the topic '{data['topic']}'.\n\n"
        
        f"DOCUMENT CONTENT:\n{document_text}\n\n"
        
        f"Additional Context: {data['description']}\n\n"
        
        f"BLOOM'S TAXONOMY LEVEL: '{blooms_level}'\n"
        f"Specific Requirement: {blooms_guidance}\n\n"
        
        f"Generate {data['number_of_questions']} questions using types: {question_type_label}, "
        f"totaling {data['total_marks']} marks.\n\n"
        
        "CRITICAL INSTRUCTIONS:\n"
        "1. Extract KEY CONCEPTS and PRINCIPLES from the document\n"
        "2. Create questions that test UNDERSTANDING of these concepts, not memorization\n"
        "3. Apply document concepts to NEW scenarios not mentioned in the PDF\n"
        "4. NEVER allow questions answerable by direct text search in the document\n"
        "5. Require explanation of WHY concepts work, not just WHAT they are\n"
        "6. For code-related content: ask students to debug, improve, or apply code to new problems\n"
        "7. Create questions requiring synthesis of multiple sections from the document\n\n"
        
        f"{type_specific_instructions}\n\n"
        
        "QUESTION PATTERNS TO USE:\n"
        "- 'The document describes concept X. Apply it to this new scenario: [novel scenario]'\n"
        "- 'Compare approaches A and B from the document. Which is better for [new context]? Why?'\n"
        "- 'A student implements [concept from doc] as follows: [code with error]. What's wrong?'\n"
        "- 'Based on principles in the document, predict what happens when [new situation]'\n"
        "- 'The document presents [concept]. Explain why it works and when NOT to use it.'\n\n"
        
        "OUTPUT FORMAT:\n"
        "Structure output strictly as a JSON array:\n"
        """[
            {
                "text": "Question applying document concepts to new scenarios/requiring analysis",
                "marks": <integer>,
                "type": "<question_type>",
                "blooms_level": "<cognitive_level>",
                "rubric": "Detailed rubric: e.g., '3 marks: correct application of concept from document, 4 marks: clear explanation of reasoning, 2 marks: justified conclusion. Partial credit for partially correct reasoning.'",
                "correct_answer": ["Comprehensive answer with reasoning, referencing document concepts"],
                "choices": null OR array_based_on_type
            }
        ]
        
        RULES FOR CHOICES:
        - open-ended: null
        - close-ended-bool: ["True", "False"]
        - close-ended-multiple-single: array of options; correct_answer = single-element array
        - close-ended-multiple-multiple: array of options; correct_answer = array with 1+ elements
        - close-ended-ordering: array to order; correct_answer = correctly ordered array
        - close-ended-matching: choices = [["source0", "source1", ...], ["target0", "target1", ...]]
        - close-ended-drag-drop: choices = [["draggable0", "draggable1", ...], ["target0", "target1", ...]]
        """
        
        f"Every question type MUST be one of: {', '.join(ALLOWED_QUESTION_TYPES)}.\n"
        "Respond ONLY with the JSON array - NO markdown, commentary, or extra text."
    )

    # response = client.chat.completions.create(
    #     model=model_deployment_name,
    #     messages=[
    #         {"role": "system", "content": system_prompt},
    #         {"role": "user", "content": user_prompt}
    #     ],
    #     max_tokens=32000,
    #     temperature=0.8,  # Increased for more creative application questions
    #     top_p=0.95,
    #     stream=False
    # )

    # return response

    content = ""

    try:
        stream = client.chat.completions.create(
            model=model_deployment_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=9000,
            temperature=0.8,
            top_p=0.95,
            stream=True
        )

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content += chunk.choices[0].delta.content

    except Exception as e:
        # Log the error and raise a more informative exception
        error_message = f"Error during AI assessment generation from PDF: {type(e).__name__}: {str(e)}"
        logger.error(error_message, exc_info=True)
        raise RuntimeError(error_message) from e

    if not content:
        error_message = "AI model returned empty content for PDF assessment"
        logger.error(error_message)
        raise RuntimeError(error_message)

    return content


def grade_image_answer(filename, question_text, rubric, correct_answer, marks, student_hobbies=None, model="gpt-4.1-mini"):
    """
    Grade an image answer using AI with emphasis on reasoning and methodology.
    Awards partial credit for correct approach even if final answer is incomplete.
    Tailors feedback based on student's hobbies to make it more engaging and relatable.
    """
    logger.info(f"[GRADE_IMAGE_ANSWER] Starting image grading - Model: {model}, Filename: {filename}, Marks: {marks}")
    logger.debug(f"[GRADE_IMAGE_ANSWER] Question: {question_text[:100]}..., Hobbies: {student_hobbies}")
    
    # read image and build a data URL
    try:
        with open(filename, "rb") as f:
            img_bytes = f.read()
        logger.info(f"[GRADE_IMAGE_ANSWER] Image file read successfully - Size: {len(img_bytes)} bytes")
    except Exception as e:
        logger.error(f"[GRADE_IMAGE_ANSWER] Failed to read image file - Error: {str(e)}")
        return {"error": "file_read_error", "detail": f"Could not read image file: {str(e)}"}, 500
    b64 = base64.b64encode(img_bytes).decode("ascii")
    mime = mimetypes.guess_type(filename)[0] or "image/png"
    data_url = f"data:{mime};base64,{b64}"
    
    system_prompt = (
        "You are an expert university examiner specializing in fair, constructive grading. "
        "Grade student responses using the rubric provided, awarding partial credit for: "
        "correct methodology, sound reasoning, proper approach, and partial solutions. "
        "Be encouraging but rigorous. Award marks for the PROCESS and THINKING, not just the final answer. "
        "Provide specific, actionable feedback that helps students improve."
    )

    # Build hobby context
    hobbies_context = ""
    if student_hobbies and isinstance(student_hobbies, (list, tuple)) and len(student_hobbies) > 0:
        hobbies_str = ", ".join(student_hobbies)
        hobbies_context = (
            f"\nSTUDENT'S INTERESTS/HOBBIES: {hobbies_str}\n"
            "When providing feedback, use examples, analogies, or references from these hobbies to explain the concepts. "
            "Make the feedback more engaging by connecting the subject matter to what the student is passionate about.\n"
        )

    user_prompt = (
        f"Grade the following image answer for this question:\n\n"
        f"QUESTION: {question_text}\n\n"
        f"MARKING RUBRIC: {rubric}\n\n"
        f"MODEL ANSWER: {correct_answer}\n\n"
        f"TOTAL MARKS AVAILABLE: {marks}\n\n"
        f"{hobbies_context}"
        
        "GRADING CRITERIA:\n"
        "1. Award marks for correct reasoning and methodology, even if the final answer is wrong\n"
        "2. Give partial credit for partially correct approaches\n"
        "3. Deduct marks for incorrect reasoning, not just incorrect final answers\n"
        "4. Consider the student's explanation and justification\n"
        "5. Be fair but maintain academic standards\n\n"
        
        "Provide a detailed explanation of the grading, identifying:\n"
        "- What the student did correctly\n"
        "- What the student did incorrectly or incompletely\n"
        "- How the marks were allocated according to the rubric\n"
        "- What was expected and where they fell short\n\n"
        
        "Return strictly as JSON:\n"
        "{ \"score\": <score_awarded_as_number>, \"feedback\": \"Detailed constructive feedback explaining the grade\" }"
    )
    
    # response = client.chat.completions.create(
    #     model=model_deployment_name_image,
    #     messages=[
    #         {"role": "system", "content": system_prompt},
    #         {"role": "user",
    #          "content": [
    #             {"type": "text", "text": user_prompt},
    #             {"type": "image_url", "image_url": {"url": image_url}}
    #          ]
    #         }
    #     ],
    #     max_tokens=800,  # Increased for more detailed feedback
    #     temperature=0.5,  # Lower for more consistent grading
    #     top_p=1.0,
    #     stream=False
    # )

    try:
        logger.info(f"[GRADE_IMAGE_ANSWER] API call starting - Model: {model}, Temperature: 0.5, Using standard chat completions API")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]}
            ],
            max_tokens=800,
            temperature=0.5,
            top_p=1.0,
            stream=False,
            timeout=60
        )
        logger.info(f"[GRADE_IMAGE_ANSWER] API call completed - Response type: {type(response)}")
        logger.debug(f"[GRADE_IMAGE_ANSWER] Full response object: {response}")
        
        # Log response attributes
        logger.debug(f"[GRADE_IMAGE_ANSWER] Response attributes - Has choices: {hasattr(response, 'choices')}, Has error: {hasattr(response, 'error')}")
        if hasattr(response, 'error'):
            logger.error(f"[GRADE_IMAGE_ANSWER] API returned error - {response.error}")
        if hasattr(response, 'choices'):
            logger.debug(f"[GRADE_IMAGE_ANSWER] Choices count: {len(response.choices)}")
    except Exception as e:
        logger.error(f"[GRADE_IMAGE_ANSWER] API call exception - Error: {str(e)}", exc_info=True)
        return {"error": "api_exception", "detail": f"API call failed: {str(e)}"}, 500

    if not hasattr(response, "choices") or len(response.choices) == 0:
        logger.error(f"[GRADE_IMAGE_ANSWER] No 'choices' in response - Has 'choices': {hasattr(response, 'choices')}")
        logger.info(f"[GRADE_IMAGE_ANSWER] Response has these content attributes: output={hasattr(response, 'output')}, output_text={hasattr(response, 'output_text')}, text={hasattr(response, 'text')}, reasoning={hasattr(response, 'reasoning')}")
        
        # Try to extract content from alternative attributes
        content = None
        if hasattr(response, 'output') and response.output:
            content = response.output
            logger.info(f"[GRADE_IMAGE_ANSWER] Extracting content from 'output' attribute - Length: {len(content)}")
        elif hasattr(response, 'output_text') and response.output_text:
            content = response.output_text
            logger.info(f"[GRADE_IMAGE_ANSWER] Extracting content from 'output_text' attribute - Length: {len(content)}")
        elif hasattr(response, 'text') and response.text:
            content = response.text
            logger.info(f"[GRADE_IMAGE_ANSWER] Extracting content from 'text' attribute - Length: {len(content)}")
        elif hasattr(response, 'reasoning') and response.reasoning:
            content = response.reasoning
            logger.info(f"[GRADE_IMAGE_ANSWER] Extracting content from 'reasoning' attribute - Length: {len(content)}")
        
        if not content:
            logger.error(f"[GRADE_IMAGE_ANSWER] No content found in any alternative attribute - Response: {response}")
            return {"error": "no_response", "detail": "No response from AI model."}, 500
    else:
        first_choice = response.choices[0]
        if not (hasattr(first_choice, "message") and hasattr(first_choice.message, "content")):
            logger.error(f"[GRADE_IMAGE_ANSWER] Invalid response format - Has 'message': {hasattr(first_choice, 'message')}")
            return {"error": "invalid_response_format",
                    "detail": "AI model did not return a properly formatted message."}, 500

        content = first_choice.message.content
        logger.info(f"[GRADE_IMAGE_ANSWER] API response content - Length: {len(content)}, Preview: {content[:150] if content else 'EMPTY'}")

    # If we got here, we have content from an alternative attribute
    logger.info(f"[GRADE_IMAGE_ANSWER] API response content - Type: {type(content)}, Length: {len(content) if content else 0}")
    
    # Convert content to string if it's a list
    if isinstance(content, list):
        logger.info(f"[GRADE_IMAGE_ANSWER] Content is a list with {len(content)} items - Converting to string")
        content = ' '.join(str(item) for item in content if item)
        logger.info(f"[GRADE_IMAGE_ANSWER] Content after list conversion - Length: {len(content)}, Preview: {content[:150] if content else 'EMPTY'}")
    elif not isinstance(content, str):
        logger.warning(f"[GRADE_IMAGE_ANSWER] Content is type {type(content)}, converting to string")
        content = str(content)
    
    # Remove markdown code blocks if present
    content = re.sub(r'```json\s*', '', content)
    content = re.sub(r'\s*```', '', content)
    logger.debug(f"[GRADE_IMAGE_ANSWER] Cleaned content: {content[:300]}...")

    match = re.search(r'\{.*\}', content, re.DOTALL)
    if not match:
        logger.error(f"[GRADE_IMAGE_ANSWER] No JSON object found in response - Raw content: {content[:500]}")
        return {"error": "no_json_object",
                "detail": "No JSON object found in model response."}, 500

    json_text = match.group(0)
    logger.debug(f"[GRADE_IMAGE_ANSWER] Extracted JSON: {json_text}")
    
    try:
        grading_result = json.loads(json_text)
        logger.info(f"[GRADE_IMAGE_ANSWER] JSON parsed successfully - Score: {grading_result.get('score')}")
    except json.JSONDecodeError as e:
        logger.error(f"[GRADE_IMAGE_ANSWER] JSON parsing failed - Error: {str(e)}, JSON text: {json_text[:200]}")
        return {"error": "invalid_json", "detail": "Unable to parse JSON from model response."}, 500

    score = grading_result.get('score')

    try:
        score = float(score)
        logger.info(f"[GRADE_IMAGE_ANSWER] Score validated - Final: {score}/{marks}")
    except (TypeError, ValueError) as e:
        logger.error(f"[GRADE_IMAGE_ANSWER] Score conversion failed - Original: {grading_result.get('score')}, Error: {str(e)}")
        return {"error": "non_numeric_score",
                "detail": f"Score '{grading_result.get('score')}' is not a valid number."}, 400

    if score < 0 or score > marks:
        logger.error(f"[GRADE_IMAGE_ANSWER] Score out of bounds - Score: {score}, Max: {marks}")
        return {"error": "score_out_of_bounds",
                "detail": f"Score {score} out of bounds (0–{marks})."}, 400

    logger.info(f"[GRADE_IMAGE_ANSWER] Grading successful - Score: {score}/{marks}")
    return grading_result, 200


def grade_text_answer(text_answer, question_text, rubric, correct_answer, marks, student_hobbies=None):
    """
    Grade a text answer using AI with emphasis on reasoning and understanding.
    Awards partial credit for sound methodology and correct reasoning process.
    Tailors feedback based on student's hobbies to make it more engaging and relatable.
    """
    logger.info(f"[GRADE_TEXT_ANSWER] Starting text grading - Model: {model_deployment_name}, Marks: {marks}")
    logger.debug(f"[GRADE_TEXT_ANSWER] Question: {question_text[:100]}..., Answer length: {len(text_answer)}, Hobbies: {student_hobbies}")
    system_prompt = (
        "You are a university examiner specializing in fair, pedagogically sound assessment. "
        "Grade student responses using the rubric, awarding marks for: correct reasoning, sound methodology, "
        "proper understanding of concepts, and valid approaches - not just final answers. "
        "Provide constructive feedback that identifies strengths and areas for improvement. "
        "Be rigorous but fair, encouraging learning while maintaining academic standards."
    )

    # Build hobby context
    hobbies_context = ""
    if student_hobbies and isinstance(student_hobbies, (list, tuple)) and len(student_hobbies) > 0:
        hobbies_str = ", ".join(student_hobbies)
        hobbies_context = (
            f"\nSTUDENT'S INTERESTS/HOBBIES: {hobbies_str}\n"
            "When providing feedback, use examples, analogies, or references from these hobbies to explain the concepts. "
            "Make the feedback more engaging by connecting the subject matter to what the student is passionate about.\n"
        )

    user_prompt = (
        f"Grade the following text answer for this question:\n\n"
        f"QUESTION: {question_text}\n\n"
        f"MARKING RUBRIC: {rubric}\n\n"
        f"MODEL ANSWER: {correct_answer}\n\n"
        f"TOTAL MARKS AVAILABLE: {marks}\n\n"
        f"STUDENT'S ANSWER:\n{text_answer}\n\n"
        f"{hobbies_context}"
        
        "GRADING INSTRUCTIONS:\n"
        "1. Evaluate the student's REASONING and UNDERSTANDING, not just the final answer\n"
        "2. Award partial credit for:\n"
        "   - Correct approach or methodology\n"
        "   - Sound reasoning even if conclusion is partially wrong\n"
        "   - Correct identification of key concepts\n"
        "   - Valid justifications and explanations\n"
        "3. Deduct marks for:\n"
        "   - Faulty reasoning or misunderstanding of concepts\n"
        "   - Missing justifications when required\n"
        "   - Incorrect methodology\n"
        "4. Consider alternative correct approaches not in the model answer\n"
        "5. Be specific about what earned or lost marks\n\n"
        
        "Provide detailed feedback that:\n"
        "- Clearly explains what was EXPECTED from the student\n"
        "- Explains what the student understood correctly\n"
        "- Explains any errors or misconceptions\n"
        "- Shows how marks were allocated per the rubric\n"
        "- Offers constructive guidance for improvement\n\n"
        
        "Return response in strict JSON format:\n"
        """{\n    "score": <numeric_score>,\n    "feedback": "Detailed explanation: [What was expected] + [What was correct] + [What was incorrect/incomplete] + [How marks were allocated] + [Suggestions for improvement]"\n}"""
    )

    response = client.chat.completions.create(
        model=model_deployment_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        max_tokens=800,  # Increased for detailed feedback
        temperature=0.5,  # Lower for consistent grading
        top_p=1.0,
        stream=False,
        timeout=30
    )
    logger.info(f"[GRADE_TEXT_ANSWER] API call completed - Model: {model_deployment_name}, Response type: {type(response)}")

    if not hasattr(response, "choices") or len(response.choices) == 0:
        logger.error(f"[GRADE_TEXT_ANSWER] No response from AI model - Has 'choices': {hasattr(response, 'choices')}, Response keys: {dir(response) if response else 'None'}")
        return {"error": "no_response", "detail": "No response from AI model."}, 500

    first_choice = response.choices[0]
    if not (hasattr(first_choice, "message") and hasattr(first_choice.message, "content")):
        logger.error(f"[GRADE_TEXT_ANSWER] Invalid response format - Has 'message': {hasattr(first_choice, 'message')}")
        return {"error": "invalid_response_format",
                "detail": "AI model did not return a properly formatted message."}, 500

    content = first_choice.message.content
    logger.info(f"[GRADE_TEXT_ANSWER] API response content - Type: {type(content)}, Length: {len(content) if content else 0}")
    
    # Convert content to string if it's a list
    if isinstance(content, list):
        logger.info(f"[GRADE_TEXT_ANSWER] Content is a list with {len(content)} items - Converting to string")
        content = ' '.join(str(item) for item in content if item)
        logger.info(f"[GRADE_TEXT_ANSWER] Content after list conversion - Length: {len(content)}, Preview: {content[:150] if content else 'EMPTY'}")
    elif not isinstance(content, str):
        logger.warning(f"[GRADE_TEXT_ANSWER] Content is type {type(content)}, converting to string")
        content = str(content)
    
    # Remove markdown code blocks if present
    content = re.sub(r'```json\s*', '', content)
    content = re.sub(r'\s*```', '', content)
    logger.debug(f"[GRADE_TEXT_ANSWER] Cleaned content: {content[:300]}...")

    match = re.search(r'\{.*\}', content, re.DOTALL)
    if not match:
        logger.error(f"[GRADE_TEXT_ANSWER] No JSON object found in response - Raw content: {content[:500]}")
        return {"error": "no_json_object",
                "detail": "No JSON object found in model response."}, 500
    
    json_text = match.group(0)
    logger.debug(f"[GRADE_TEXT_ANSWER] Extracted JSON: {json_text}")

    try:
        grading_result = json.loads(json_text)
        logger.info(f"[GRADE_TEXT_ANSWER] JSON parsed successfully - Score: {grading_result.get('score')}")
    except json.JSONDecodeError as e:
        logger.error(f"[GRADE_TEXT_ANSWER] JSON parsing failed - Error: {str(e)}, JSON text: {json_text[:200]}")
        return {"error": "invalid_json", "detail": "Unable to parse JSON from model response."}, 500

    score = grading_result.get('score')
    logger.info(f"[GRADE_TEXT_ANSWER] Score extracted: {score} (type: {type(score)})")

    try:
        score = float(score)
        logger.info(f"[GRADE_TEXT_ANSWER] Score validated - Final: {score}/{marks}")
    except (TypeError, ValueError) as e:
        logger.error(f"[GRADE_TEXT_ANSWER] Score conversion failed - Original: {grading_result.get('score')}, Error: {str(e)}")
        return {"error": "non_numeric_score",
                "detail": f"Score '{grading_result.get('score')}' is not a valid number."}, 400

    if score < 0 or score > marks:
        logger.error(f"[GRADE_TEXT_ANSWER] Score out of bounds - Score: {score}, Max: {marks}")
        return {"error": "score_out_of_bounds",
                "detail": f"Score {score} out of bounds (0–{marks})."}, 400

    logger.info(f"[GRADE_TEXT_ANSWER] Grading successful - Score: {score}/{marks}")
    return grading_result, 200
