# Aria

## Docker

1. Install Docker Desktop:
   `https://www.docker.com/products/docker-desktop/`

### Setup

1. Start db in background (separate postgres instance from your local one running on port 5433):

   `docker compose up db -d`

2. Start backend

   `docker compose up django --build`
   
   or to start in background: `docker compose up django --build -d`
   
3. Run the db setup script

   `docker compose exec django bash -c ./first_run.sh`
   
   The default admin and staff accounts from `.env` (`DEFAULT_ADMIN_*`, `DEFAULT_STAFF_*`)
   are created automatically the first time the backend starts.

4. After making a change stop and rebuild the backend

5. Go to:

   `127.0.0.1:8000`

### Running
1. Make sure db is running (might already be running)

`docker compose up db -d`

2. Run backend
`docker compose up --build django`

3. If it mentions something about migrations or there is some error after an update
`docker exec django python manage.py migrate`

### Stopping
`docker compose down`

Or individually:

`docker compose down db`

`docker compose down django`

## No Docker

### Setup

1. Create virtual environment:

   `python -m venv ./venv`

2. Enter environment:

   `.\venv\Scripts\activate`

3. Install requirements:

   `pip install -r requirements.txt`

4. Copy the `.env.example` file to `.env` in the repo root and fill in the values
   (database, sample account password, default admin/staff logins)

### Running

1. Apply migrations if needed:

   `cd aria_project`

   `python manage.py migrate`

2. Create the default admin and staff accounts from `.env` (safe to run again, existing accounts are left alone):

   `python manage.py create_default_accounts`

3. Run the project:

   `python manage.py runserver`
---

## Project Structure

### Accounts

Accounts will contain register/login as well as account information and edit account functionality.

### Cart

Cart will contain the shopping cart as well as the entire checkout process.

### Products

Products will contain the browse products page and product details.

### Core

Core will contain pages like the home page and about page.

---

## Database Design Process and Rationale

For Phase 1, we created the EERD using Lucidchart. The database design was developed around the requirements of the Aria system and the relationships between customers, staff, products, orders, payments, inventory, refunds, suppliers, carriers, and policy documents.

The following assumptions and key decisions were made during the database design process.

## Database Design Assumptions and Key Decisions

1. We use separate `Category` and `Address` tables to avoid duplication of data in the event where two customers may share the same address.

2. An `inventory_movements` table is included for keeping a log of stock changes such as regular sales, returns, restocking, and adjustments.

3. The database currently supports only CAD and USD. However, this check constraint can easily be changed in the future if desired.

4. The `policy_documents` table stores metadata for documents that we want accessible to the RAG chatbot. From there, we can automate the updating of the vector database based on the contents of this table, such as through a Python script.

5. For payment tracking, our database is using two separate tables: `accounts_payable` and `accounts_receivable`.

6. A separate `refunds` table is included, as one of the main goals of the database redesign was simplifying the refund process. This allows us to have specific metadata and status tracking for each refund.

7. An `order_items` table is used so that orders can support multiple products and quantities, and this can be easily queried.

8. A `carriers` table is used for storing a name, description, and, importantly, a tracking URL template for each carrier that we may ship with.

9. For payments, we decided to disjoint our payment types, which allows us to make certain types of payments follow a specific rule set. Having the payment types disjointed also allows for each type to be mutually exclusive.

10. Another disjointed subtype we implemented was for payees, which can either be a supplier for the business or a carrier we contracted. A payee can either be one or the other, not both.

11. Using accounts as a supertype, we chose to have staff and customer overlap because a staff member could be a customer, and a customer could be a staff member.

12. We decided that it made sense for payments and orders to have an aggregate relationship because one cannot exist without the other.

---

## Proposal Revisions

1. **High-volume data source:** Customer transactions, as well as read operations for product details.

2. **Docker use justification:** Docker makes consistent and reproducible deployments easier, especially if we are deploying in a cloud environment.

---

## Modelling Tools

The EERD was created using **Lucidchart**.

---

## Team Member Contributions

| Team Member | Role | Responsibilities | Specific Contributions This Phase |
|---|---|---|---|
| Ethan Pelletier | Backend / Integration Lead | Backend and integration of database with Django | Repository creation / code push |
| Brayden Nickel | Modelling Lead | Create EERD | EERD, design choices, and assumptions |
| Drew Temple-Smith | Big Data / Analytics / DB Lead | Data Dictionary | Assisted with the Data Dictionary and technical report writing |
| Kyle Castillo | QA / UX Lead | Assist in the creation of the EERD diagram | Assisted with the EERD diagram |
