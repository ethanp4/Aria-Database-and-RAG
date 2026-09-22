# Aria
## Setup
### No docker
1. Create virtual environment 
``python -m venv ./venv``
2. Enter environment 
``.\venv\Scripts\activate``
3. Install requirements
``pip install -r requirements.txt``
4. Run create_db_and_user.sql and schema.sql in your posgresql to make the db. Copy the .env.example to .env
### Docker
1. Install docker desktop ``https://www.docker.com/products/docker-desktop/``

## Running
### No docker
1. Apply migrations if it complains<br>
   ``cd aria_project``<br>
   ``python manage.py migrate``
2. Run project<br>
``python manage.py runserver``
### Docker
1. ``docker compose up``
2. Go to 127.0.0.1:8080