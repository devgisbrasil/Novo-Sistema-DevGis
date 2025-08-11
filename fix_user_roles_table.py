from app import create_app, db
from app.models import UserRole
from datetime import datetime

def add_assigned_at_column():
    app = create_app()
    with app.app_context():
        try:
            # Check if the column already exists
            from sqlalchemy import inspect, text
            
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('user_roles')]
            
            if 'assigned_at' not in columns:
                print("Adding 'assigned_at' column to 'user_roles' table...")
                # Add the column with a default value
                db.session.execute(text("""
                    ALTER TABLE user_roles 
                    ADD COLUMN assigned_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                """))
                db.session.commit()
                print("Successfully added 'assigned_at' column to 'user_roles' table.")
                
                # Update existing rows with the current timestamp
                print("Updating existing records with current timestamp...")
                db.session.execute(text("""
                    UPDATE user_roles 
                    SET assigned_at = CURRENT_TIMESTAMP 
                    WHERE assigned_at IS NULL
                """))
                db.session.commit()
                print("Successfully updated existing records.")
            else:
                print("'assigned_at' column already exists in 'user_roles' table.")
                
        except Exception as e:
            db.session.rollback()
            print(f"Error: {str(e)}")
            print("Please check if the database is running and accessible.")

if __name__ == "__main__":
    add_assigned_at_column()
