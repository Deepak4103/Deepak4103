# College Attendance (Django)

Work in progress. Phase 1 (admin setup and logins) is complete.

## Quick start (local)
```bash
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_demo          # creates the default admin + sample data
python manage.py runserver
```
Open http://127.0.0.1:8000/

Default admin: **admin** / **Admin@12345** (you are forced to change it at first login).
Demo faculty: **ravi**, **sneha**, **anil** / **Faculty@123**.

Run tests: `python manage.py test`

The full README (hosting steps, etc.) is written in the final phase.
