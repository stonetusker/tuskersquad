from apps.backend.database import engine,Base,SessionLocal
from apps.backend.models import Product


def seed():

    Base.metadata.create_all(bind=engine)

    db=SessionLocal()

    if db.query(Product).count()==0:

        db.add_all([

            Product(name="Laptop",price=1000),

            Product(name="Mouse",price=50),

            Product(name="Keyboard",price=120)

        ])

        db.commit()

    db.close()


if __name__=="__main__":

    seed()
