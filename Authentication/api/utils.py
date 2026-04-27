from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from flask import current_app
from dotenv import load_dotenv
import random
import string
import os

load_dotenv()

valid_domains = ['uonbi.ac.ke', 'mu.ac.ke', 'ku.ac.ke', 'jkuat.ac.ke', 'egerton.ac.ke', 'maseno.ac.ke', 'mmust.ac.ke',
                 'tukenya.ac.ke', 'tum.ac.ke', 'dkut.ac.ke', 'chuka.ac.ke', 'karatinauniversity.ac.ke', 'kisiiuniversity.ac.ke',
                 'mmarau.ac.ke', 'pu.ac.ke', 'seku.ac.ke', 'jooust.ac.ke', 'kibu.ac.ke', 'laikipia.ac.ke', 'mksu.ac.ke', 'must.ac.ke',
                 'mmu.ac.ke', 'mut.ac.ke', 'embuni.ac.ke', 'uoeld.ac.ke', 'kabianga.ac.ke', 'cuk.ac.ke', 'gau.ac.ke', 'rongovarsity.ac.ke',
                 'ttu.ac.ke', 'kyu.ac.ke', 'au.ac.ke', 'kafu.ac.ke', 'tmu.ac.ke', 'tharaka.ac.ke', 'ouk.ac.ke', 'ndu.ac.ke', 'buc.ac.ke',
                 'ksu.ac.ke', 'mnu.ac.ke', 'tuc.ac.ke', 'unika.ac.ke', 'strathmore.edu', 'usiu.ac.ke', 'daystar.ac.ke', 'mku.ac.ke', 'cuea.edu',
                 'anu.ac.ke', 'spu.ac.ke', 'kabarak.ac.ke', 'kca.ac.ke', 'kemu.ac.ke', 'zetech.ac.ke', 'pacuniversity.ac.ke', 'aiu.ac.ke', 'iuk.ac.ke',
                 'tangaza.ac.ke', 'ueab.ac.ke', 'umma.ac.ke', 'aku.edu', 'aua.ac.ke', 'east.ac.ke', 'scott.ac.ke', 'kwust.ac.ke', 'kheu.ac.ke',
                 'lukenyauniversity.ac.ke', 'gluk.ac.ke', 'puea.ac.ke', 'teau.ac.ke', 'amref.ac.ke', 'riarauniversity.ac.ke', 'mua.ac.ke',
                 'gretsauniversity.ac.ke', 'piu.ac.ke', 'uzimauniversity.ac.ke', 'kenya.ilu.edu', 'riu.ac.ke', 'miuc.ac.ke', 'kgs.ac.ke',
                 'nairobipoly.ac.ke', 'kisumupoly.ac.ke', 'tenp.ac.ke', 'kabetepolytechnic.ac.ke', 'nyerinationalpoly.ac.ke', 'sigalagalapoly.ac.ke',
                 'mnp.ac.ke', 'kitalenationalpolytechnic.ac.ke', 'kenyacoastpoly.ac.ke', 'kisiipoly.ac.ke', 'baringonationalpolytechnic.ac.ke',
                 'nyandaruanationalpoly.ac.ke', 'mawegopoly.ac.ke', 'bumbepoly.ac.ke', 'kerichopoly.ac.ke', 'wotetti.ac.ke', 'kerokatechnical.ac.ke',
                 'michukitech.ac.ke', 'sikriblinddeaf.ac.ke', 'okametvc.ac.ke', 'gatundusouthtvc.ac.ke', 'sist.ac.ke', 'tonp.ac.ke', 'kgs.ac.ke',
                 'ndu.ac.ke', 'ndu.ac.ke/niruc', 'ndu.ac.ke/ndc', 'ndu.ac.ke/dchs', 'ipstc.org', 'gmail.com'
                ]

def hashing_password(password: str) -> str:
    """
    Uses Werkzeug’s PBKDF2+SHA256 to hash the given password.
    """
    return generate_password_hash(password)


def compare_password(hashed_pwd: str, password: str) -> bool:
    """
    Verifies a plaintext password against the stored hash.
    """
    return check_password_hash(hashed_pwd, password)


def is_valid_institution_email(email: str) -> bool:
    """
    Validates if the email belongs to a recognized educational institution domain.
    """
    try:
        domain = email.split('@')[1].lower()
        # check if also for subdomains added to the domain e.g student.uonbi.ac.ke. check for pattern ending with valid domain
        for valid_domain in valid_domains:
            if domain == valid_domain or domain.endswith('.' + valid_domain):
                return True
        return False
    except IndexError:
        return False

# JWT token revocation store
revoked_tokens = set()

def add_revoked_token(jti: str):
    """
    Adds a token to the revoked tokens set.
    """
    revoked_tokens.add(jti)


def is_token_revoked(jti: str) -> bool:
    """
    Checks if a token is revoked by its jti (JWT ID).
    """
    return jti in revoked_tokens

def education_quotes_random_generator():
    """
    returns random education quotes from the list
    """
    quotes = [
      "The more that you read, the more things you will know, the more that you learn, the more places you’ll go. —Dr. Seuss",
      "Education is one thing no one can take away from you. —Elin Nordegren",
      "A simple but powerful reminder of the positive domino effect a good education can have on many aspects of a person’s life and outlook.",
      "Education is the key that unlocks the golden door to freedom. —George Washington Carver",
      "Give a man a fish and you feed him for a day; teach a man to fish and you feed him for a lifetime. —Maimonides",
      "Education’s purpose is to replace an empty mind with an open one. —Malcolm Forbes",
      "Education is what remains after one has forgotten what one has learned in school. —Albert Einstein",
      "Education is not preparation for life; education is life itself. —John Dewey",
      "The aim of education is the knowledge, not of facts, but of values. —William S. Burroughs",
      "What makes a child gifted and talented may not always be good grades in school, but a different way of looking at the world and learning. —Chuck Grassley",
      "“Education is the vaccine of violence. —Edward James Olmos",
      "Learning is not compulsory… Neither is survival. —W. Edwards Demin",
      "The purpose of education is to turn mirrors into windows. —Sydney J. Harris",
      "Intelligence plus character — that is the goal of true education. —Martin Luther King Jr",
      "Education is the most powerful weapon which you can use to change the world. —Nelson Mandela",
      "A child without education is like a bird without wings. —Tibetan Proverb",
      "The purpose of learning is growth, and our minds, unlike our bodies, can continue growing as we continue to live. —Mortimer Adler",
      "The ability to read, write, and analyze; the confidence to stand up and demand justice and equality; the qualifications and connections to get your foot in the door and take your seat at the table — all of that starts with education. —Michelle Obama",
      "The principal goal of education in the schools should be creating men and women who are capable of doing new things, not simply repeating what other generations have done. —Jean Piaget",
      "The content of a book holds the power of education and it is with this power that we can shape our future and change lives. —Malala Yousafzai",
      "Education makes a people easy to lead but difficult to drive; easy to govern, but impossible to enslave. —Peter Brougham",
      "The goal of education is the advancement of knowledge and the dissemination of truth. —John F. Kennedy",
      "Knowledge is power. Information is liberating. Education is the premise of progress in every society, in every family. —Kofi Annan",
      "Education is the passport to the future, for tomorrow belongs to those who prepare for it today. —Malcolm X",
      "Whatever the cost of our libraries, the price is cheap compared to that of an ignorant nation. ―Walter Cronkite",
      "We learn from failure, not from success!― Bram Stoker",
      "Learning is not attained by chance; it must be sought for with ardor and diligence.– Abigail Adams",
      "Continuous learning is the minimum requirement for success in any field.  — Brian Tracy",
      "Life is a succession of lessons which must be lived to be understood. – Helen Keller",
      "The only place success comes before work is in the dictionary. – Vince Lombardi"
    ]

    index = random.randint(0, len(quotes) - 1)
    return quotes[index]

# send notification email to the user after creating an account successfully
def send_account_creation_email(to_email: str, reciever_fname: str, reciever_lname: str) -> bool:
    try:
        quote = education_quotes_random_generator()
        mail = Mail(current_app)
        # Control SMTP debugging based on configuration
        if not current_app.config.get('MAIL_DEBUG', False):
            # Disable SMTP debugging to prevent verbose output
            import smtplib
            smtplib.SMTP.debuglevel = 0
        msg = Message("Welcome to the IntelliMark!",
                    sender=os.getenv('MAIL_USERNAME'),
                    recipients=[to_email])
        msg.body = f"""
    Dear {reciever_lname} {reciever_fname},

    Welcome to the IntelliMark! Your account has been created successfully.
    You can now log in using your institutional email.

        link: https://intellimark.pages.dev/

    We look forward to supporting your learning journey.

    {quote}

    Thank you,
    UAMAS Team
    """
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def generate_numeric_code(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def generate_join_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choices(alphabet, k=length))


def send_verification_email(to_email: str, verification_code: str) -> bool:
    try:
        mail = Mail(current_app)
        if not current_app.config.get('MAIL_DEBUG', False):
            import smtplib
            smtplib.SMTP.debuglevel = 0
        msg = Message(
            "IntelliMark Email Verification",
            sender=os.getenv('MAIL_USERNAME'),
            recipients=[to_email]
        )
        msg.body = (
            f"Your IntelliMark verification code is: {verification_code}\n\n"
            "This code will expire in 15 minutes. If you did not request this, "
            "you can ignore this email."
        )
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Failed to send verification email: {e}")
        return False
    
# # email notification for lecturers password reset by their own request
def send_password_reset_email(to_email: str, reciever_fname: str, reciever_lname: str) -> bool:
    try:
        mail = Mail(current_app)
        # Control SMTP debugging based on configuration
        if not current_app.config.get('MAIL_DEBUG', False):
            # Disable SMTP debugging to prevent verbose output
            import smtplib
            smtplib.SMTP.debuglevel = 0
        msg = Message("IntelliMark Password Reset",
                    sender=os.getenv('MAIL_USERNAME'),
                    recipients=[to_email])
        msg.body = f"""
    Dear {reciever_lname} {reciever_fname},

    Your password has been reset successfully.
    If you did not request this change, please contact support immediately.

    Thank you,
    UAMAS Team
    """
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False
