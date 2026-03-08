"""
Seed the demo database with realistic test data.
"""
from apps.backend.database import engine, Base, SessionLocal
from apps.backend.models import Product, User
from apps.backend.auth import hash_password


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            db.add_all([
                User(email="test@example.com",   password=hash_password("password")),
                User(email="admin@shopflow.io",  password=hash_password("admin123")),
                User(email="demo@tuskersquad.io",password=hash_password("password")),
            ])
            db.commit()

        if db.query(Product).count() == 0:
            db.add_all([
                Product(name="Pro Laptop 16\"",      price=1299.00),
                Product(name="Mechanical Keyboard",  price=149.99),
                Product(name="4K Monitor 27\"",      price=449.00),
                Product(name="Wireless Mouse",       price=59.99),
                Product(name="USB-C Hub 10-in-1",    price=79.99),
                Product(name="Noise-Cancel Headset", price=299.00),
                Product(name="WebCam Pro HD",        price=119.00),
                Product(name="Desk Pad XL",          price=34.99),
            ])
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
