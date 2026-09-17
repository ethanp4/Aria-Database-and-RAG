# Aria
### Setup
1. Create virtual environment 
``python -m venv ./venv``
2. Enter environment 
``.\venv\Scripts\activate``
3. Install requirements
``pip install -r requirements.txt``
4. Run create_db_and_user.sql and schema.sql in your posgresql to make the db. Copy the .env.example to .env

### Running

1. Apply migrations (if database changes were made)<br>
   ``cd aria_project``<br>
   ``python manage.py migrate``
2. Run project<br>
``python manage.py runserver``