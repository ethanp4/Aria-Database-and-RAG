# Aria

## Project structure
### Accounts
Accounts will contain register / login as well as account info / edit account
### Cart
Cart will contain the shopping cart as well as the entire checkout process
### Products
Products will contain the browse products page and product details
### Core
Core will contain pages like the home page and about page

## Setup
### No docker
1. Create virtual environment 
``python -m venv ./venv``
2. Enter environment 
``.\venv\Scripts\activate``
3. Install requirements
``pip install -r requirements.txt``
4. Run create_db_and_user.sql and schema.sql in your posgresql to make the db. Copy the .env.example to aria_project/aria/.env
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
1. ``docker compose up --build``
2. Go to 127.0.0.1:8080