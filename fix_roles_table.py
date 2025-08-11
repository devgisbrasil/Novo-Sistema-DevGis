from app import create_app, db
from app.models import Role
from sqlalchemy import text

app = create_app()

with app.app_context():
    # Check if the description column exists
    try:
        # This will fail if the column doesn't exist
        Role.query.with_entities(Role.description).first()
        print("Description column already exists in roles table")
    except Exception as e:
        if 'column roles.description does not exist' in str(e):
            print("Adding description column to roles table...")
            # Add the description column using text() for raw SQL
            db.session.execute(text('ALTER TABLE roles ADD COLUMN IF NOT EXISTS description TEXT'))
            db.session.commit()
            print("Successfully added description column to roles table")
        else:
            print(f"Error: {e}")
