# College Attendance Management

A web application for marking and managing **period-wise student attendance** in a college. Faculty mark
attendance from their phones; the admin sets everything up, monitors it, handles leave and substitutions, and
downloads reports.

* Python 3.10+ and Django, SQLite database (easy to move to PostgreSQL), simple server-rendered pages.
* Works on phones and desktops. Two roles only: **Admin** and **Faculty** (no student login).
* Passwords are stored hashed (PBKDF2). Each role only sees its own pages.

---

## 1. What it does

**Admin**
- Classes, students (manual entry or Excel/CSV upload), subjects, faculty accounts (reset password, deactivate), allotment of faculty to subjects.
- Timetable per class: upload an Excel/CSV, preview it, edit it in a weekly grid. Each timetable has an *effective-from* date, so changing it never disturbs past records.
- Holidays, leave types and yearly leave days, forenoon/afternoon split, shortage threshold (default 75%).
- Monitoring dashboard: for any date, which periods have attendance and which are pending, with the faculty name.
- Edit any attendance record; unlock a locked one for the faculty.
- Leave: enter leave for anyone (even a past date), approve/reject, make/change/cancel any adjustment, "Unadjusted periods" list.
- Seven reports, each filterable by class, subject, faculty and dates, and exportable to Excel and PDF.

**Faculty**
- Log in with user ID and password, change own password.
- Home screen: today's periods (Pending / Completed) and a highlighted list of pending periods from today and earlier days.
- Mark attendance: everyone starts Present, tap to mark Absent, live present/absent count, the topic covered is compulsory.
- Edit own entry the same day; after that it is locked (the admin can unlock).
- View past attendance and logs of own subjects.
- Apply for leave (full day, half day or specific periods), choose a substitute and subject for every period, see the leave balance.
- Accept or decline when a colleague asks them to take a period; adjusted periods appear in their list as *"Adjustment for <name>"*.

---

## 2. Run it on your computer

You need **Python 3.10 or newer** ([python.org/downloads](https://www.python.org/downloads/); on Windows tick *"Add Python to PATH"* during install).

1. **Get the code** and open a terminal in the `attendance_app` folder.
   ```bash
   git clone https://github.com/Deepak4103/Deepak4103.git
   cd Deepak4103
   git checkout claude/student-attendance-management-9tjmjk     # or the branch you merged it into
   cd attendance_app
   ```
   (No git? On GitHub choose the branch, click **Code → Download ZIP**, unzip, and open a terminal in the `attendance_app` folder.)

2. **Create a virtual environment and install the requirements.**
   - Mac / Linux
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     pip install -r requirements.txt
     ```
   - Windows (Command Prompt)
     ```bat
     python -m venv .venv
     .venv\Scripts\activate
     pip install -r requirements.txt
     ```

3. **Create the database and load the sample data.**
   ```bash
   python manage.py migrate
   python manage.py load_demo
   ```

4. **Start the server.**
   ```bash
   python manage.py runserver
   ```
   Open **http://127.0.0.1:8000/** in your browser. Press `Ctrl+C` in the terminal to stop it.

5. **Log in.**

   | Role | User ID | Password |
   |---|---|---|
   | **Admin** (default account) | `admin` | `Admin@12345` — you must change it at first login |
   | Faculty (sample) | `ravi`, `sneha`, `anil` | `Faculty@123` |

**Try it on your phone** (same Wi-Fi as the computer): start the server with
`python manage.py runserver 0.0.0.0:8000`, find the computer's IP address (e.g. `192.168.1.5`) and open
`http://192.168.1.5:8000/` on the phone.

### The sample data
2 classes (CSE II Year Sem 1, Sections A and B) with 10 students each, 3 subjects each, 3 faculty, a Monday–Saturday
timetable (6 periods a day), about a week of attendance (some periods deliberately left pending, two students per class
with poor attendance so the shortage list has entries), four leave types and one approved leave with substitutes
(one on the same subject, one on a different subject). The dates are relative to the day you run `load_demo`.

### Starting for real (without the sample data)
```bash
rm db.sqlite3                 # Windows: del db.sqlite3     (deletes the demo data)
python manage.py migrate
python manage.py ensure_admin # creates the default admin if none exists
```
Then log in as `admin`, change the password, and follow the order in section 3. Leave types (Casual, Medical, Earned, On Duty) are created by `load_demo`; for a clean start add yours under **Leave → Leave types**.

To pick your own first admin login: `ADMIN_USER_ID=principal ADMIN_PASSWORD='Something-Strong-1' python manage.py ensure_admin`.
Forgot an admin password? `python manage.py changepassword admin`.

### Run the automated tests
```bash
python manage.py test
```
232 tests cover the rules that are easy to get wrong: attendance percentages (classes actually held, under the subject
actually taught), substitute eligibility, duplicate entries, locking of past records, leave balances, consent flow,
reports and exports.

---

## 3. Setting up a real college (admin, in this order)

1. **Classes** → add each class (name, branch, year, semester, section).
2. Open a class → **Add subject** for each subject (name + code). Use the *same code* for the same subject in different sections (this is how "same subject taught to another class" is recognised).
3. **Faculty** → create accounts (name, user ID, password). Tell faculty their login; they can change the password themselves.
4. Open a class → **Allot faculty** to each subject.
5. Open a class → **Students**: add manually or **Bulk upload**. Template columns: `roll_no, name`. Roll numbers are unique across the whole college. You get a preview and a list of problem rows before anything is saved.
6. Open a class → **Timetable** → download the blank template, fill it in, upload it, check the preview, save, then fine-tune in the weekly grid.
   Template columns: `day, period, start_time, end_time, subject, faculty` — day = Mon…Sat, period = 1–7, times like `09:00`, *subject* = subject code, *faculty* = faculty User ID. A period must have the same times on every day, and a teacher cannot be in two classes in the same period.
7. **Holidays** → add holidays / non-working days (whole college or one class). Sundays are automatic.
8. **Leave → Leave types** → set days per year; **Leave → Forenoon / afternoon** (Settings) → which periods are forenoon (default periods 1–4); the same page holds the shortage threshold.

To change the timetable from a future date, use **New version (grid)** with that effective-from date — past attendance is never touched.

---

## 4. Host it online so faculty can use it from their phones

The app is a normal website. It must be served over **HTTPS** (both options below do this for you). Two easy options:

### Option A — PythonAnywhere (simplest; keeps SQLite)

PythonAnywhere has a free plan that is enough for a small college trial (check their current free-plan rules, e.g. that a free
web app must be re-confirmed from time to time). Replace `USERNAME` below with your PythonAnywhere username.

1. Create an account at **pythonanywhere.com**. Your site will be `https://USERNAME.pythonanywhere.com`.
2. **Consoles → Bash.** Get the code and create the environment:
   ```bash
   git clone https://github.com/Deepak4103/Deepak4103.git
   cd Deepak4103
   git checkout claude/student-attendance-management-9tjmjk        # or your merged branch
   cd attendance_app
   mkvirtualenv --python=python3.12 attendance                      # use a Python version PythonAnywhere offers (3.10+)
   pip install -r requirements.txt
   ```
3. **Create the database and admin** (still in the console; pick your own strong admin password):
   ```bash
   python manage.py migrate
   ADMIN_PASSWORD='Choose-A-Strong-One-1' python manage.py ensure_admin
   DEBUG=0 python manage.py collectstatic --noinput
   ```
   (Use `python manage.py load_demo` instead of `ensure_admin` if you first want to try it with the sample data.)
4. **Web tab → Add a new web app → Manual configuration** → same Python version. Then set:
   - *Source code* and *Working directory*: `/home/USERNAME/Deepak4103/attendance_app`
   - *Virtualenv*: `/home/USERNAME/.virtualenvs/attendance`
   - *Static files* (optional, faster): URL `/static/` → directory `/home/USERNAME/Deepak4103/attendance_app/staticfiles`
5. Click the **WSGI configuration file** link and replace its contents with:
   ```python
   import os, sys

   path = '/home/USERNAME/Deepak4103/attendance_app'
   if path not in sys.path:
       sys.path.insert(0, path)

   os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
   os.environ['DEBUG'] = '0'
   os.environ['SECRET_KEY'] = 'paste-a-long-random-string-here'
   os.environ['ALLOWED_HOSTS'] = 'USERNAME.pythonanywhere.com'
   os.environ['CSRF_TRUSTED_ORIGINS'] = 'https://USERNAME.pythonanywhere.com'

   from django.core.wsgi import get_wsgi_application
   application = get_wsgi_application()
   ```
   (Generate the secret key with: `python -c "import secrets; print(secrets.token_urlsafe(50))"`.)
6. **Web tab → green Reload button.** Open `https://USERNAME.pythonanywhere.com`, log in as `admin`, change the password and set up your college (section 3).
7. **Share the link** with faculty. On a phone they can use the browser menu → *Add to Home Screen* to get an app-like icon.

**Updating later:** in a Bash console `cd ~/Deepak4103/attendance_app && git pull && pip install -r requirements.txt && python manage.py migrate && DEBUG=0 python manage.py collectstatic --noinput`, then press **Reload**.

**Backups:** your data is the file `attendance_app/db.sqlite3`. Download it regularly from the **Files** tab (or copy it: `cp db.sqlite3 backup-$(date +%F).sqlite3`).

### Option B — Render (or similar: Railway, Fly.io) with PostgreSQL

Free web hosts usually do not keep local files, so use a PostgreSQL database there.

1. In `requirements.txt` remove the `#` in front of `psycopg[binary]`, commit and push.
2. On **render.com**: *New → PostgreSQL* (copy its *Internal Database URL*), then *New → Web Service* from your GitHub repo with:
   - Root directory: `attendance_app`
   - Build command: `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate && python manage.py ensure_admin`
   - Start command: `gunicorn config.wsgi`
   - Environment variables: `DEBUG=0`, `SECRET_KEY=<long random string>`, `ALLOWED_HOSTS=<your-service>.onrender.com`, `CSRF_TRUSTED_ORIGINS=https://<your-service>.onrender.com`, `DATABASE_URL=<the Internal Database URL>`, `ADMIN_PASSWORD=<strong password>`
3. Deploy, open the URL, log in as `admin` (password = your `ADMIN_PASSWORD`; you will be asked to change it).

> I could not test a live deployment from the environment this was built in. I did test it in production mode locally
> (`DEBUG=0`, `collectstatic`, `gunicorn`, host checking, static files). If a host-specific step fails, the troubleshooting
> list below covers the common causes.

### Security checklist before real use
- Change the default admin password immediately (you are forced to at first login).
- Set a real `SECRET_KEY` and `DEBUG=0` in production (the examples above do).
- Serve over HTTPS only. Back up the database regularly.
- Only create faculty accounts yourself; there is no self-registration.

### Moving from SQLite to PostgreSQL later
1. Uncomment `psycopg[binary]` in `requirements.txt` and `pip install -r requirements.txt`.
2. Export the existing data: `python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.permission -o data.json`
3. Set `DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/DBNAME`, run `python manage.py migrate`, then `python manage.py loaddata data.json`.

---

## 5. Rules built into the app

- Attendance is recorded **per period**. The same class + date + period cannot be entered twice (enforced in the database).
- **Percentages are calculated from classes actually held** (periods whose attendance was entered), grouped by the **subject actually taught** — never from the timetable. A student added mid-term is not penalised for periods held before they joined. "Shortage" means strictly below the threshold (exactly 75% is not a shortage).
- Faculty can mark only periods that are theirs (or that they are substituting), only for today or earlier days, and never on holidays or Sundays. A pending period from an earlier day can still be completed; editing is allowed on the day of the class or the day it was entered, then it locks until the admin unlocks it (an unlock lasts until the faculty re-saves).
- **Leave:** workload adjustment is compulsory. A leave lists every affected period (holidays skipped). Each needs a substitute and a subject (same, or different from the class's subjects). It cannot be submitted until all are filled. Substitutes are **eligible** only if they teach any subject to that class or the same subject (same code or name) to another class, are free in that period per the timetable, are not on leave, and are not already committed to another substitution then. The substitute must accept; if one declines the applicant picks someone else; once all accept it goes to the admin. Admin-made adjustments need no acceptance (the substitute is notified).
- On the leave day, an adjusted period appears in the substitute's list marked *Adjustment for <name>*, is no longer pending for the faculty on leave, and the attendance and topic are counted under the subject actually taught and credited to the substitute.
- **Leave balance:** deducted when the admin approves; full day = 1 day, half day or specific periods = 0.5 day; Sundays and holidays are not counted; you get a warning when the balance is exhausted or exceeded (the admin decides).
- Each attendance record keeps the timetable subject and faculty as they were, so timetable changes never rewrite history.

Settings you can change in `config/settings.py`: `PERIODS_PER_DAY` (7), `WORKING_DAYS` (6 = Mon–Sat), `PENDING_LOOKBACK_DAYS` (30), `TIME_ZONE` (Asia/Kolkata).

## 6. Reports (admin → Reports)
Student-wise attendance · Class-wise and subject-wise summary · Daily report · Shortage list · Faculty log · Leave and adjustment register · Faculty workload. All can be filtered by class, subject, faculty and date range and downloaded as Excel or PDF. (PDF uses a standard Latin font; names in other scripts appear correctly in Excel and on screen but may not in PDF.)

## 7. Troubleshooting
- **"CSRF verification failed" when logging in online** → set `CSRF_TRUSTED_ORIGINS=https://your-site-address`.
- **"Bad Request (400)" online** → add your site's host name to `ALLOWED_HOSTS` (comma separated).
- **Page has no styling online** → run `DEBUG=0 python manage.py collectstatic --noinput` and reload.
- **Server error right after an update** → run `python manage.py migrate`, then reload.
- **A faculty member cannot be chosen as substitute** → they must be eligible (see the rule above) and free in that period; check their timetable and leave.
- **Timetable upload rejected** → the preview lists every problem line; the usual causes are a subject code that is not in that class, a faculty User ID that does not exist, or a teacher already teaching another class at that time.

## 8. Project layout
```
config/      settings, urls
accounts/    users, login, roles, faculty accounts
academics/   classes, students, subjects, allotment, holidays, settings, demo data
timetable/   timetable versions, upload/preview, weekly grid
attendance/  attendance marking, pending prompt, locking, monitoring
leaves/      leave types, requests, eligibility, consent, approval, balances, notifications
reports/     the seven reports and Excel/PDF export
templates/ static/
```
