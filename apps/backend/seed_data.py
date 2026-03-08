"""
Seed the demo database with test data.
Creates tables, a test user, and sample products on first run.
"""

from apps.backend.database import engine, Base, SessionLocal
from apps.backend.models import Product, User
from apps.backend.auth import hash_password


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Seed test user (used by agents for login probes)
        if db.query(User).count() == 0:
            db.add(User(
                email="test@example.com",
                password=hash_password("password"),
            ))
            db.commit()

        # Seed products
        if db.query(Product).count() == 0:
            db.add_all([
                Product(name="Laptop", price=1000.0),
                Product(name="Mouse", price=50.0),
                Product(name="Keyboard", price=120.0),
            ])
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
